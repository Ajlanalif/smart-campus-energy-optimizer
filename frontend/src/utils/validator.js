/**
 * Independent GridWise Physics & Guardrails Validator
 * Replays and validates the schedule against canonical rules from the problem statement:
 * 1. Hourly Energy Balance: grid + solar_used + discharge = demand + charge (within 0.01 kWh)
 * 2. Effective Solar Bound: solar_used <= effective_solar
 * 3. Battery Transitions: E_after = E_before + charge - discharge
 * 4. Battery Bounds: active_min_reserve <= E_after <= capacity
 * 5. Battery Rate Limits: charge <= max_charge, discharge <= max_discharge
 * 6. Directive Application: no_charge, no_discharge, max_grid, minimum_battery_reserve
 * 7. End-of-Day Neutrality: E_after[23] == initial_energy_kwh
 * 8. Recalculated Totals: total_grid_kwh, total_cost_bdt, peak_grid_kwh match hourly_plan
 */

export function validateSchedule(scenario, response) {
  const errors = [];
  const warnings = [];
  const checks = {
    schemaValid: false,
    energyBalance: false,
    batteryTransitions: false,
    batteryBounds: false,
    batteryRateLimits: false,
    solarBounds: false,
    directivesFollowed: false,
    endOfDayNeutrality: false,
    totalsMatch: false,
  };

  if (!scenario || !response) {
    return { isValid: false, errors: ['Missing scenario or response data'], warnings, checks };
  }

  const { hours, battery } = scenario;
  const { hourly_plan, directive_interpretation, total_grid_kwh, total_cost_bdt, peak_grid_kwh } = response;

  if (!Array.isArray(hourly_plan) || hourly_plan.length !== 24) {
    errors.push(`hourly_plan must contain exactly 24 entries (received ${hourly_plan?.length})`);
    return { isValid: false, errors, warnings, checks };
  }

  checks.schemaValid = true;

  // Build effective solar array
  const effectiveSolar = hours.map(h => h.solar_kwh);
  const activeMinReserve = Array(24).fill(battery.minimum_energy_kwh);
  const noChargeHours = new Set();
  const noDischargeHours = new Set();
  const maxGridCap = Array(24).fill(Infinity);

  if (Array.isArray(directive_interpretation)) {
    directive_interpretation.forEach((item) => {
      if (item.applies && item.structured_adjustment) {
        const adj = item.structured_adjustment;
        const targetHours = Array.isArray(adj.hours) ? adj.hours : [];

        if (item.directive_type === 'solar_reduction') {
          const factor = typeof adj.factor === 'number' ? adj.factor : 1.0;
          targetHours.forEach(h => {
            if (h >= 0 && h < 24) effectiveSolar[h] = hours[h].solar_kwh * factor;
          });
        } else if (item.directive_type === 'minimum_battery_reserve') {
          const minKwh = adj.minimum_energy_kwh || battery.minimum_energy_kwh;
          targetHours.forEach(h => {
            if (h >= 0 && h < 24) activeMinReserve[h] = Math.max(activeMinReserve[h], minKwh);
          });
        } else if (item.directive_type === 'no_charge_window') {
          targetHours.forEach(h => noChargeHours.add(h));
        } else if (item.directive_type === 'no_discharge_window') {
          targetHours.forEach(h => noDischargeHours.add(h));
        } else if (item.directive_type === 'max_grid_window') {
          const cap = typeof adj.max_grid_kwh === 'number' ? adj.max_grid_kwh : Infinity;
          targetHours.forEach(h => {
            if (h >= 0 && h < 24) maxGridCap[h] = Math.min(maxGridCap[h], cap);
          });
        }
      }
    });
  }

  let energyBalancePass = true;
  let batteryTransitionsPass = true;
  let batteryBoundsPass = true;
  let batteryRateLimitsPass = true;
  let solarBoundsPass = true;
  let directivesFollowedPass = true;

  let prevBattery = battery.initial_energy_kwh;
  let recalcGrid = 0;
  let recalcCost = 0;
  let recalcPeak = 0;

  for (let h = 0; h < 24; h++) {
    const plan = hourly_plan[h];
    const hourData = hours[h];

    if (!plan || plan.hour !== h) {
      errors.push(`Hour ${h}: Missing or misplaced plan entry`);
      continue;
    }

    const grid = plan.grid_kwh;
    const solarUsed = plan.solar_used_kwh;
    const action = plan.battery_action;
    const batteryKwh = plan.battery_kwh;
    const batteryAfter = plan.battery_energy_after_kwh;
    const demand = hourData.demand_kwh;
    const tariff = hourData.tariff_bdt_per_kwh;

    // Recalculations
    recalcGrid += grid;
    recalcCost += grid * tariff;
    if (grid > recalcPeak) recalcPeak = grid;

    // 1. Solar bound
    if (solarUsed < -0.01 || solarUsed > effectiveSolar[h] + 0.01) {
      solarBoundsPass = false;
      errors.push(`Hour ${h}: solar_used (${solarUsed} kWh) exceeds effective solar (${effectiveSolar[h].toFixed(2)} kWh)`);
    }

    // 2. Battery rate limits
    if (action === 'charge' && batteryKwh > battery.max_charge_kwh_per_hour + 0.01) {
      batteryRateLimitsPass = false;
      errors.push(`Hour ${h}: Charge amount (${batteryKwh}) exceeds max_charge (${battery.max_charge_kwh_per_hour})`);
    }
    if (action === 'discharge' && batteryKwh > battery.max_discharge_kwh_per_hour + 0.01) {
      batteryRateLimitsPass = false;
      errors.push(`Hour ${h}: Discharge amount (${batteryKwh}) exceeds max_discharge (${battery.max_discharge_kwh_per_hour})`);
    }
    if (action === 'idle' && Math.abs(batteryKwh) > 0.01) {
      batteryRateLimitsPass = false;
      errors.push(`Hour ${h}: Idle action must have battery_kwh = 0 (got ${batteryKwh})`);
    }

    // 3. Energy balance: grid + solar_used + discharge = demand + charge
    const chargeAmt = action === 'charge' ? batteryKwh : 0;
    const dischargeAmt = action === 'discharge' ? batteryKwh : 0;
    const generation = grid + solarUsed + dischargeAmt;
    const load = demand + chargeAmt;

    if (Math.abs(generation - load) > 0.02) {
      energyBalancePass = false;
      errors.push(`Hour ${h}: Energy balance violation: generation (${generation.toFixed(2)}) != load (${load.toFixed(2)})`);
    }

    // 4. Battery transitions
    let expectedAfter = prevBattery;
    if (action === 'charge') expectedAfter += batteryKwh;
    if (action === 'discharge') expectedAfter -= batteryKwh;

    if (Math.abs(batteryAfter - expectedAfter) > 0.02) {
      batteryTransitionsPass = false;
      errors.push(`Hour ${h}: Battery transition mismatch: reported ${batteryAfter} vs computed ${expectedAfter.toFixed(2)}`);
    }

    // 5. Battery bounds
    if (batteryAfter < activeMinReserve[h] - 0.02 || batteryAfter > battery.capacity_kwh + 0.02) {
      batteryBoundsPass = false;
      errors.push(`Hour ${h}: Battery level ${batteryAfter} violates bounds [${activeMinReserve[h]}, ${battery.capacity_kwh}]`);
    }

    // 6. Directives adherence
    if (noChargeHours.has(h) && action === 'charge' && batteryKwh > 0.01) {
      directivesFollowedPass = false;
      errors.push(`Hour ${h}: Violated no_charge_window directive`);
    }
    if (noDischargeHours.has(h) && action === 'discharge' && batteryKwh > 0.01) {
      directivesFollowedPass = false;
      errors.push(`Hour ${h}: Violated no_discharge_window directive`);
    }
    if (grid > maxGridCap[h] + 0.02) {
      directivesFollowedPass = false;
      errors.push(`Hour ${h}: Grid import (${grid}) exceeds directive cap (${maxGridCap[h]})`);
    }

    prevBattery = batteryAfter;
  }

  // 7. End-of-day neutrality
  const lastHourPlan = hourly_plan[23];
  let endOfDayPass = false;
  if (lastHourPlan) {
    if (Math.abs(lastHourPlan.battery_energy_after_kwh - battery.initial_energy_kwh) <= 0.02) {
      endOfDayPass = true;
    } else {
      errors.push(`End-of-day battery neutrality violation: Final level ${lastHourPlan.battery_energy_after_kwh} kWh != initial ${battery.initial_energy_kwh} kWh`);
    }
  }

  // 8. Totals check
  let totalsMatchPass = true;
  if (Math.abs(total_grid_kwh - recalcGrid) > 0.05) {
    totalsMatchPass = false;
    errors.push(`total_grid_kwh mismatch: reported ${total_grid_kwh} vs recalculated ${recalcGrid.toFixed(2)}`);
  }
  if (Math.abs(total_cost_bdt - recalcCost) > 0.05) {
    totalsMatchPass = false;
    errors.push(`total_cost_bdt mismatch: reported ${total_cost_bdt} vs recalculated ${recalcCost.toFixed(2)}`);
  }
  if (Math.abs(peak_grid_kwh - recalcPeak) > 0.05) {
    totalsMatchPass = false;
    errors.push(`peak_grid_kwh mismatch: reported ${peak_grid_kwh} vs recalculated ${recalcPeak.toFixed(2)}`);
  }

  checks.energyBalance = energyBalancePass;
  checks.batteryTransitions = batteryTransitionsPass;
  checks.batteryBounds = batteryBoundsPass;
  checks.batteryRateLimits = batteryRateLimitsPass;
  checks.solarBounds = solarBoundsPass;
  checks.directivesFollowed = directivesFollowedPass;
  checks.endOfDayNeutrality = endOfDayPass;
  checks.totalsMatch = totalsMatchPass;

  const isValid = errors.length === 0;

  return {
    isValid,
    errors,
    warnings,
    checks,
    recalculated: {
      total_grid_kwh: Number(recalcGrid.toFixed(2)),
      total_cost_bdt: Number(recalcCost.toFixed(2)),
      peak_grid_kwh: Number(recalcPeak.toFixed(2)),
    }
  };
}
