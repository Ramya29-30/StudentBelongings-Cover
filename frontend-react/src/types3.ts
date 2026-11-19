export interface Category {
  id: number; name: string; description: string; min_purchase_value: number; monthly_premium: number; annual_premium: number; max_coverage: number; deductible: number;
  policy_months: number; waiting_period_days: number; depreciation_pct_per_year: number; depreciation_max_pct: number; exclusions: string[]; covered_incident_types: string[];
  excluded_damage_types: string[]; damage_types: string[]; reference_repair_costs: Record<string, number>; eligibility_conditions: string; requires_serial: boolean; active: boolean;
}
export interface Quote {
  category: string; purchase_value: number; monthly_premium: number; annual_premium: number; max_coverage: number; estimated_max_claim: number; deductible: number; policy_months: number;
  waiting_period_days: number; exclusions: string[]; covered_incident_types: string[]; formula: { annual_premium: string; estimated_max_claim: string };
}
export interface Eligibility { eligible: boolean; reason: string; quote: Quote | null; active_policy?: boolean }
export interface AssetV3 {
  id: number; category: string; category_id: number; name: string; brand: string; model_name: string; description: string; serial_number: string; purchase_date: string; purchase_price: number;
  has_invoice: boolean; has_photo: boolean; invoice_verified: boolean; invoice_status: string; eligibility_status: string; eligibility_reason: string;
  policy: { id: number; policy_number: string; status: string; max_coverage: number; monthly_premium: number } | null;
  evidence_status: string; can_purchase: boolean; evidence?: EvidenceSummary;
}
export interface EvidenceFile {
  id: number; kind: string; label: string; original_name: string; content_type: string; size_bytes: number; width: number; height: number; uploaded_at: string; review_status: string;
  is_image: boolean; quality_issues: string[]; file_url: string;
  sha256?: string; flags?: { code: string; severity: string; text: string }[]; exif?: Record<string, string>; reviewed_at?: string | null;
}
export interface EvidenceSummary {
  status: string; note: string; reviewed_at: string | null; missing_required: string[]; has_invoice: boolean; counts: Record<string, number>; can_purchase: boolean; can_add: boolean;
  reason: string; files: EvidenceFile[]; identifier_note?: string;
}
export interface EvidenceQueueRow {
  id: number; name: string; category: string; owner: string; purchase_price: number; created_at: string; evidence_status: string; files: number; missing_required: string[];
  has_invoice: boolean; flags: { high: number; medium: number; low: number }; insured: boolean;
}
export interface DeviceMatch {
  status: string; band: string; best_score: number | null; method: string; conclusion: string; supporting_evidence: string[]; limitations: string[]; used_for_routing?: boolean;
  registered_photos_used: string[]; thresholds?: { strong: number; partial: number; note: string };
  pairs: { claim_image: string; reference: string; good_matches: number; inliers: number; score: number }[];
  serial_check?: { status: string; detail: string; method: string | null }; brand_model_check?: { status: string; detail: string; method: string | null };
}
export interface ReportSummary {
  expected_device_present: { status: string | null; detail: string | null }; visible_damage: { status: string; types: string[]; top_confidence: number | null };
  description_matches: string; registered_device_match: { band: string | null; score: number | null; used_for_routing: boolean | null };
  authenticity_flags: { high: number; medium: number; low: number }; note: string;
}
export interface AuthImage { image: string; sha256: string; width: number; height: number; megapixels: number; format: string | null; exif: { present: boolean; camera: string | null; software: string | null; captured: string | null; gps_present: boolean; editing_software: boolean }; ela: { applicable: boolean; uneven: boolean; reason: string }; notes: string[] }
export interface Authenticity { images?: AuthImage[]; indicator_count?: number; limitations?: Record<string, string>; missing_exif_policy?: string; summary?: ReportSummary }
export interface PolicyV3 {
  id: number; policy_number: string; status: string; start_date: string; end_date: string; category: string | null; asset_id: number | null; asset_name: string | null; student_name?: string;
  purchase_value: number; monthly_premium: number; annual_premium: number; max_coverage: number; deductible: number; premiums_paid: number; next_premium_due: string | null;
  terms: { exclusions: string[]; covered_incident_types: string[]; waiting_period_days: number; policy_months: number } | null;
}
export interface Tx { id: number; reference: string; policy_number: string; amount: number; period: string; status: string; method: string; paid_at: string; simulated: boolean }
export interface Check { id: string; name: string; result: string; reason: string }
export interface Detection { damage_type: string; confidence: number | null; box: number[] | null; source: string }
export interface QualityImage { image: string; usable: boolean; score: number; issues: string[] }
export interface Report {
  id: number; run: number; mode: string; is_simulated: boolean; model_info: Record<string, unknown>;
  quality: { images: QualityImage[]; usable_count: number; total_count: number; average_score: number; result: string };
  asset_identification: { status: string; detected: string | null; confidence: number | null; match: string; method?: string | null; explanation: string };
  damage_detection: { status: string; method?: string | null; detections: Detection[]; explanation: string };
  description_check: { result: string; notes: string[]; method: string };
  duplicate_check: { result: string; note?: string };
  evidence_completeness: { photos_uploaded?: number; usable_photos?: number; supporting_documents?: number; description_provided?: boolean; complete?: boolean };
  risk_indicators: { code: string; severity: string; text: string }[];
  device_match?: DeviceMatch; authenticity?: Authenticity; summary?: ReportSummary | null; workflow_outcome: string;
  outcome: string; route: string; explanation: string; next_step: string; processing_ms: number; created_at: string;
}
export interface CalcLine { label: string; amount: number; note: string }
export interface Decision {
  outcome: string; decided_by: string; checks: Check[]; payable_amount: number | null; reason: string; created_at: string;
  calculation: { payable?: number; lines?: CalcLine[]; basis?: string; binding_limit?: string };
}
export interface ClaimV3 {
  id: number; claim_number: string; status: string; asset_id: number; asset_name: string; asset_category: string; policy_number: string; claimant_name: string; incident_date: string;
  incident_type: string; damage_type: string; description: string; estimated_repair_cost: number | null; assessed_loss: number | null; payable_amount: number | null; ai_outcome: string; ai_workflow_outcome?: string | null; awaiting_staff_confirmation?: boolean;
  decision_outcome: string; decision_reason: string; created_at: string;
  images?: { id: number; original_name: string; size_bytes: number; width: number; height: number }[]; report?: Report | null; report_count?: number; decision?: Decision | null;
  settlement?: { reference: string; amount: number; status: string; simulated: boolean; settled_at: string | null } | null; history?: { from: string; to: string; reason: string; at: string }[];
}
export interface Capabilities { effective_mode: string; note: string; asset_model: { file: string } | null; damage_model: { file: string } | null; vision_language_model: boolean }
