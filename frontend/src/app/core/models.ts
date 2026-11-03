export type Role = 'ADMIN' | 'OPERATOR';
export type EventStatus =
  'RECEIVED' | 'PROCESSING' | 'RETRYING' | 'SUCCEEDED' | 'FAILED' | 'IGNORED';
export type DeliveryStatus = 'PENDING' | 'PROCESSING' | 'RETRYING' | 'SUCCEEDED' | 'FAILED';
export type AttemptOutcome = 'IN_PROGRESS' | 'SUCCESS' | 'RETRYABLE_ERROR' | 'PERMANENT_ERROR';
export type HttpMethod = 'POST' | 'PUT' | 'PATCH';

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface MembershipSummary {
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: Role;
}

export interface Me {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
  memberships: MembershipSummary[];
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  role: Role | null;
}

export interface Member {
  id: string;
  user_id: string;
  email: string;
  full_name: string;
  role: Role;
  created_at: string;
}

export interface AuditLog {
  id: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  details: Record<string, unknown>;
  actor_user_id: string | null;
  actor_email: string | null;
  created_at: string;
}

export interface RouteInfo {
  id: string;
  endpoint_id: string;
  destination_id: string;
  destination_name: string;
  transform_rule_id: string | null;
  transform_rule_name: string | null;
  is_active: boolean;
  created_at: string;
}

export interface Endpoint {
  id: string;
  name: string;
  description: string | null;
  public_id: string;
  ingest_url: string;
  secret_preview: string;
  secret_rotated_at: string | null;
  previous_secret_expires_at: string | null;
  event_id_path: string;
  is_active: boolean;
  routes: RouteInfo[];
  created_at: string;
  updated_at: string;
}

export interface EndpointWithSecret extends Endpoint {
  signing_secret: string;
}

export interface SecretOut {
  signing_secret: string;
  previous_secret_expires_at: string | null;
}

export interface Destination {
  id: string;
  name: string;
  description: string | null;
  url: string;
  method: HttpMethod;
  headers: Record<string, string>;
  timeout_seconds: number;
  max_attempts: number;
  is_active: boolean;
  has_signing_secret: boolean;
  created_at: string;
  updated_at: string;
}

export type MappingType = 'keep' | 'string' | 'integer' | 'float' | 'boolean' | 'datetime';
export type MappingTransform = 'lower' | 'upper' | 'trim';

export interface Mapping {
  target: string;
  source?: string | null;
  value?: unknown;
  default?: unknown;
  type?: MappingType;
  transform?: MappingTransform | null;
  required?: boolean;
}

export interface TransformRule {
  id: string;
  name: string;
  description: string | null;
  include_unmapped: boolean;
  mappings: Mapping[];
  sample_payload: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface PreviewResponse {
  valid: boolean;
  output: unknown;
  errors: string[];
}

export interface DeliverySummary {
  id: string;
  event_id: string;
  external_event_id: string;
  endpoint_id: string;
  endpoint_name: string;
  destination_id: string;
  destination_name: string;
  status: DeliveryStatus;
  attempt_count: number;
  max_attempts: number;
  last_status_code: number | null;
  last_error: string | null;
  next_attempt_at: string | null;
  replay_count: number;
  created_at: string;
  updated_at: string;
  succeeded_at: string | null;
  failed_at: string | null;
}

export interface Attempt {
  id: string;
  attempt_number: number;
  trigger: 'AUTO' | 'MANUAL' | 'RECOVERY';
  outcome: AttemptOutcome;
  request_url: string;
  request_method: string;
  status_code: number | null;
  error_type: string | null;
  error_message: string | null;
  response_excerpt: string | null;
  duration_ms: number | null;
  next_retry_at: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface DeliveryDetail extends DeliverySummary {
  transform_rule_id: string | null;
  transformed_payload: unknown;
  attempts: Attempt[];
}

export interface EventSummary {
  id: string;
  endpoint_id: string;
  endpoint_name: string;
  external_event_id: string;
  event_id_source: string;
  status: EventStatus;
  payload_size: number;
  duplicate_count: number;
  delivery_count: number;
  received_at: string;
}

export interface EventDetail extends EventSummary {
  payload: unknown;
  headers: Record<string, string>;
  source_ip: string | null;
  last_duplicate_at: string | null;
  deliveries: DeliverySummary[];
}

export interface ReplayResponse {
  replayed: number;
  delivery_ids: string[];
}

export interface TimeBucket {
  bucket: string;
  received: number;
  succeeded: number;
  failed: number;
}

export interface DestinationHealth {
  destination_id: string;
  destination_name: string;
  succeeded: number;
  failed: number;
  pending: number;
  success_rate: number | null;
}

export interface DashboardSummary {
  period_hours: number;
  events_received: number;
  duplicates_blocked: number;
  deliveries_total: number;
  deliveries_succeeded: number;
  deliveries_failed: number;
  deliveries_pending: number;
  deliveries_retrying: number;
  success_rate: number | null;
  avg_attempt_duration_ms: number | null;
  outbox_pending: number;
  timeline: TimeBucket[];
  destinations: DestinationHealth[];
  recent_failures: DeliverySummary[];
}

export type SimulatorMode = 'normal' | 'error' | 'timeout' | 'rate_limit';

export interface SimulatorControl {
  mode: SimulatorMode;
  status_code: number;
  delay_seconds: number;
  retry_after: number;
  fail_next: number | null;
  remaining_failures: number | null;
}

export interface SimulatorRequest {
  id: string;
  received_at: string;
  hook: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
  mode: SimulatorMode;
  response_status: number | null;
}

export interface SimulatorRequests {
  total_received: number;
  matched: number;
  succeeded: number;
  unique_successful_deliveries: number;
  items: SimulatorRequest[];
}
