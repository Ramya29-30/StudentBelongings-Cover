// =====================================================================================================================
// StudentBelongingsCover - Gosu port of the pure rule and calculation logic
//
// STATUS: NOT COMPILED, NOT EXECUTED. No Gosu compiler or Guidewire environment was available when this was written.
//   * Only java.* types and core Gosu language constructs are used. NOTHING here calls a Guidewire API.
//   * The value classes below (PolicyFacts, ClaimFacts, RuleResult) are plain classes defined in this file. They are
//     NOT Guidewire entities. In a real PolicyCenter/ClaimCenter project you would fill them from real entities in an
//     adapter layer (see docs/GUIDEWIRE_MAPPING.md, "Adapter layer"); that adapter is deliberately NOT written here
//     because its entity and property names cannot be verified without a Guidewire data dictionary.
//   * The Python code is the reference implementation (backend/app/engine/rules.py and calculator.py). If this file
//     and the Python disagree, the Python (which has automated tests) is right.
//
// The previous version of this file used invented names (SbcPolicy, SbcClaim, policy.versionEffectiveOn(...), an
// undefined RuleResult). Those are removed.
// =====================================================================================================================
package sbc.rules

uses java.math.BigDecimal
uses java.math.RoundingMode
uses java.util.Date
uses java.util.List

/** Facts about the policy version in force on the loss date. Plain data holder - not a Guidewire entity. */
class PolicyFacts {
  var _startDate : Date as StartDate
  var _endDate : Date as EndDate
  var _activatedOn : Date as ActivatedOn        // null while the policy has never been activated
  var _cancelledOn : Date as CancelledOn        // null if not cancelled
  var _insuredAssetIds : List<Long> as InsuredAssetIds
  var _coveredPerils : List<String> as CoveredPerils
}

/** Facts about the claim being checked. Plain data holder - not a Guidewire entity. */
class ClaimFacts {
  var _incidentDate : Date as IncidentDate
  var _incidentType : String as IncidentType
  var _assetId : Long as AssetId
}

/** Result of one rule. Plain data holder. Outcome is one of PASS, FAIL, PENDING (subset of the Python outcomes). */
class RuleResult {
  var _ruleId : String as RuleId
  var _outcome : String as Outcome
  var _reason : String as Reason
  construct(ruleId : String, outcome : String, reason : String) {
    _ruleId = ruleId
    _outcome = outcome
    _reason = reason
  }
}

class ClaimRules {

  /** Python: cover_start(). Cover begins on the later of the start date and the activation date. */
  static function coverStart(p : PolicyFacts) : Date {
    if (p.ActivatedOn == null) {
      return null
    }
    return p.StartDate.after(p.ActivatedOn) ? p.StartDate : p.ActivatedOn
  }

  /** POL-001: policy in force on the INCIDENT date (not today). */
  static function policyActiveOnIncidentDate(p : PolicyFacts, c : ClaimFacts) : RuleResult {
    var start = coverStart(p)
    var d = c.IncidentDate
    var inForce = start != null
        and not d.before(start)
        and not d.after(p.EndDate)
        and (p.CancelledOn == null or d.before(p.CancelledOn))
    return new RuleResult("POL-001", inForce ? "PASS" : "FAIL",
        inForce ? "Policy was in force on the incident date" : "Policy was not in force on the incident date")
  }

  /** POL-002: asset insured in the policy version in force on the incident date. */
  static function assetInsured(p : PolicyFacts, c : ClaimFacts) : RuleResult {
    var ok = p.InsuredAssetIds.contains(c.AssetId)
    return new RuleResult("POL-002", ok ? "PASS" : "FAIL",
        ok ? "Asset is insured under the applicable policy version" : "Asset was not insured under the applicable policy version")
  }

  /** POL-003: incident type must be a covered peril. */
  static function coveredPeril(p : PolicyFacts, c : ClaimFacts) : RuleResult {
    var ok = p.CoveredPerils.contains(c.IncidentType)
    return new RuleResult("POL-003", ok ? "PASS" : "FAIL", ok ? "Covered peril" : "Not a covered peril")
  }

  /** Depreciation percentage: min(maxPct, ratePerYearPct * completedYears). Python: calculate_claim(), depreciation step. */
  static function depreciationPct(ratePerYearPct : BigDecimal, maxPct : BigDecimal, completedYears : int) : BigDecimal {
    return maxPct.min(ratePerYearPct.multiply(new BigDecimal(completedYears)))
  }

  /**
   * Payable amount after the per-item limit has already been applied to 'amount'.
   *   limitThenDeductible = true  (baseline):  max(0, min(amount, remainingOverallLimit) - deductible)
   *   limitThenDeductible = false:             min(max(0, amount - deductible), remainingOverallLimit)
   * Pass remainingOverallLimit = null for "no overall limit". Money is rounded to 2 places, half-up.
   * Example (must hold): 4500.00 with deductible 1000.00 and ample limit -> 3500.00
   */
  static function payable(amount : BigDecimal, deductible : BigDecimal, remainingOverallLimit : BigDecimal,
                          limitThenDeductible : boolean) : BigDecimal {
    var result : BigDecimal
    if (limitThenDeductible) {
      var capped = remainingOverallLimit == null ? amount : amount.min(remainingOverallLimit)
      result = capped.subtract(deductible).max(BigDecimal.ZERO)
    } else {
      var afterDeductible = amount.subtract(deductible).max(BigDecimal.ZERO)
      result = remainingOverallLimit == null ? afterDeductible : afterDeductible.min(remainingOverallLimit)
    }
    return result.setScale(2, RoundingMode.HALF_UP)
  }
}
