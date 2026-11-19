export type Role = 'student' | 'admin' | 'assessor';

export interface User { id: number; username: string; full_name: string; role: Role; email: string | null; is_active?: boolean; last_login_at?: string | null }
export interface Session extends User { csrf_token: string; expires_at: string }

export interface Meta {
  asset_categories: string[]; incident_types: string[]; damage_types: string[]; severities: string[]; repair_actions: string[];
  doc_types: string[]; confidence: string[]; policy_statuses: string[]; claim_statuses: string[];
}
export interface Asset {
  id: number; owner_id: number; owner_name: string | null; category: string; name: string; make_model: string; serial_number: string;
  purchase_date: string; declared_value: number; proof_of_purchase_ref: string; added_on?: string;
}
export interface Exclusion { code: string; title: string; clause: string; incident_types: string[]; damage_types: string[]; severities: string[] }
export interface Terms {
  plan_name: string; covered_perils: string[]; overall_limit: number; default_per_item_limit: number | null; per_item_limits: Record<string, number>;
  cap_at_declared_value: boolean; deductible_type: 'fixed' | 'percent'; deductible_value: number; calc_order: string;
  depreciation: { enabled?: boolean; rate_per_year_pct?: number; max_pct?: number; applies_to?: string };
  waiting_period_days: number; required_documents: Record<string, string[]>; duplicate_window_days: number;
  repair_replace_threshold_pct: number; disabled_rules: string[]; exclusions: Exclusion[];
}
export interface Plan extends Terms { id: number; name: string; description: string; wording: string }
export interface PolicyVersion { version: number; effective_from: string; reason: string; created_at: string; plan_name: string; insured_asset_ids: number[]; terms: Terms }
export interface Policy {
  id: number; policy_number: string; student_id: number; student_name: string; plan_id: number; plan_name: string; status: string;
  start_date: string; end_date: string; activated_on: string | null; cancelled_on: string | null; cancellation_reason: string;
  asset_count: number; current_version: number; assets?: Asset[]; versions?: PolicyVersion[]; wording?: string;
}
export interface RuleResult { rule_id: string; rule_name: string; outcome: string; inputs: Record<string, unknown>; reason: string; clause: string; follow_up: string; item_id: number | null }
export interface CalcLine { seq: number; kind: string; label: string; amount: number; running_total: number | null; rule_ref: string; note: string; item_id: number | null }
export interface Evaluation {
  run: number; policy_version: number; recommendation: string; recommendation_reasons: string[]; rule_results: RuleResult[];
  calculation_lines: CalcLine[]; estimated_payable: number | null; stale?: boolean; calculation_summary?: CalcSummary;
}
export interface CalcSummary {
  gross_total: number; excluded_total: number; depreciation_total: number; eligible_subtotal: number; per_item_adjustment: number; overall_adjustment: number;
  deductible_applied: number; estimated_payable: number; uncovered_total: number; uncovered: { reason: string; amount: number }[];
  per_item: { item_id: number; gross: number | null; eligible: number; priced: boolean; excluded?: string }[]; flags: string[]; calc_order: string;
}
export interface ClaimItem {
  id: number; component: string; damage_type: string; severity: string; repair_action: string; parts_cost: number | null; labour_cost: number | null;
  price_source: string; catalogue_entry_id: number | null; evidence_refs: number[]; confidence: string; verification_status: string; notes: string;
  decision_reason: string; ai_suggestion_id: number | null;
}
export interface EvidenceFile { id: number; doc_type: string; original_name: string; content_type: string; size_bytes: number; uploaded_at: string }
export interface Claim {
  id: number; claim_number: string; policy_id: number; policy_number: string; claimant_id: number; claimant_name: string; asset_id: number; asset_name: string;
  asset_category: string; incident_date: string; incident_type: string; incident_location: string; description: string; status: string;
  policy_version_used: number | null; recommendation: string; recommendation_reasons: string[]; estimated_payable: number | null;
  assessor_notes: string; decision_reason: string; created_at: string; submitted_at: string | null; assessor_id: number | null;
  items?: ClaimItem[]; evidence?: EvidenceFile[]; evaluation?: Evaluation | null; allowed_transitions?: string[];
  status_history?: { from: string; to: string; reason: string; changed_at: string; changed_by: string }[];
}
export interface CatalogueEntry { id: number; category: string; component: string; damage_type: string; action: string; parts_cost: number; labour_cost: number; notes: string; active: boolean }
export interface AISuggestion {
  id: number; kind: string; is_ai: boolean; provider: string; model: string; status_note: string; label: string; content: Record<string, any>;
  accepted: boolean; created_at: string; meta?: Record<string, any>; validation_status: string; evidence_id: number | null; verify_notice?: string;
}
export interface AIStatus { provider: string; configured: boolean; text_model: string | null; vision_model: string | null; vision_available: boolean; message: string }
export interface PaymentEvent { from: string; to: string; reason: string; by: string | null; at: string }
export interface Payment {
  id: number; claim_id: number; claim_number?: string; reference: string; amount: number; status: string; payee_name: string; method: string; simulated: boolean;
  notes: string; requested_by: string | null; requested_at: string; decided_by: string | null; decision_reason: string; simulation_note: string; events: PaymentEvent[];
}
export interface Finance {
  notice: string; claim_status: string; payments: Payment[]; paid_total_simulated: number; estimated_payable?: number | null; recommended_reserve?: number;
  approved_reserve?: number; committed?: number; remaining_reserve?: number;
  history?: { action: string; field: string; old: number; new: number; reason: string; by: string | null; at: string }[];
}
export interface AuditRow { id: number; entity_type: string; entity_id: number; claim_id: number | null; action: string; detail: Record<string, unknown>; username: string; created_at: string }
