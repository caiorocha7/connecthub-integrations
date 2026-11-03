import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AuditLog,
  DashboardSummary,
  DeliveryDetail,
  DeliverySummary,
  Destination,
  Endpoint,
  EndpointWithSecret,
  EventDetail,
  EventSummary,
  Mapping,
  Me,
  Member,
  Organization,
  Page,
  PreviewResponse,
  ReplayResponse,
  Role,
  RouteInfo,
  SecretOut,
  TokenResponse,
  TransformRule,
} from './models';

export type QueryParams = Record<string, string | number | boolean | null | undefined>;

export function toParams(query: QueryParams = {}): HttpParams {
  let params = new HttpParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== '') {
      params = params.set(key, String(value));
    }
  }
  return params;
}

/** Thin typed client for the ConnectHub REST API (all calls are tenant-scoped by org id). */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/v1';

  private org(orgId: string): string {
    return `${this.base}/orgs/${orgId}`;
  }

  // ---------------------------------------------------------------- auth
  login(email: string, password: string): Observable<TokenResponse> {
    return this.http.post<TokenResponse>(`${this.base}/auth/login`, { email, password });
  }
  register(body: {
    email: string;
    password: string;
    full_name: string;
    organization_name?: string | null;
  }): Observable<TokenResponse> {
    return this.http.post<TokenResponse>(`${this.base}/auth/register`, body);
  }
  refresh(refreshToken: string): Observable<TokenResponse> {
    return this.http.post<TokenResponse>(`${this.base}/auth/refresh`, {
      refresh_token: refreshToken,
    });
  }
  logout(refreshToken: string): Observable<void> {
    return this.http.post<void>(`${this.base}/auth/logout`, { refresh_token: refreshToken });
  }
  me(): Observable<Me> {
    return this.http.get<Me>(`${this.base}/auth/me`);
  }
  updateMe(fullName: string): Observable<Me> {
    return this.http.patch<Me>(`${this.base}/auth/me`, { full_name: fullName });
  }
  changePassword(current: string, next: string): Observable<void> {
    return this.http.post<void>(`${this.base}/auth/change-password`, {
      current_password: current,
      new_password: next,
    });
  }

  // ---------------------------------------------------------------- organizations
  listOrgs(): Observable<Organization[]> {
    return this.http.get<Organization[]>(`${this.base}/orgs`);
  }
  createOrg(name: string): Observable<Organization> {
    return this.http.post<Organization>(`${this.base}/orgs`, { name });
  }
  getOrg(orgId: string): Observable<Organization> {
    return this.http.get<Organization>(this.org(orgId));
  }
  updateOrg(orgId: string, name: string): Observable<Organization> {
    return this.http.patch<Organization>(this.org(orgId), { name });
  }
  members(orgId: string): Observable<Member[]> {
    return this.http.get<Member[]>(`${this.org(orgId)}/members`);
  }
  addMember(orgId: string, email: string, role: Role): Observable<Member> {
    return this.http.post<Member>(`${this.org(orgId)}/members`, { email, role });
  }
  updateMember(orgId: string, membershipId: string, role: Role): Observable<Member> {
    return this.http.patch<Member>(`${this.org(orgId)}/members/${membershipId}`, { role });
  }
  removeMember(orgId: string, membershipId: string): Observable<void> {
    return this.http.delete<void>(`${this.org(orgId)}/members/${membershipId}`);
  }
  auditLogs(orgId: string, query: QueryParams): Observable<Page<AuditLog>> {
    return this.http.get<Page<AuditLog>>(`${this.org(orgId)}/audit-logs`, {
      params: toParams(query),
    });
  }

  // ---------------------------------------------------------------- endpoints
  endpoints(orgId: string): Observable<Endpoint[]> {
    return this.http.get<Endpoint[]>(`${this.org(orgId)}/endpoints`);
  }
  endpoint(orgId: string, id: string): Observable<Endpoint> {
    return this.http.get<Endpoint>(`${this.org(orgId)}/endpoints/${id}`);
  }
  createEndpoint(
    orgId: string,
    body: { name: string; description?: string | null; event_id_path?: string },
  ): Observable<EndpointWithSecret> {
    return this.http.post<EndpointWithSecret>(`${this.org(orgId)}/endpoints`, body);
  }
  updateEndpoint(orgId: string, id: string, body: Partial<Endpoint>): Observable<Endpoint> {
    return this.http.patch<Endpoint>(`${this.org(orgId)}/endpoints/${id}`, body);
  }
  deleteEndpoint(orgId: string, id: string): Observable<void> {
    return this.http.delete<void>(`${this.org(orgId)}/endpoints/${id}`);
  }
  rotateSecret(orgId: string, id: string, graceMinutes: number): Observable<SecretOut> {
    return this.http.post<SecretOut>(`${this.org(orgId)}/endpoints/${id}/rotate-secret`, {
      grace_period_minutes: graceMinutes,
    });
  }
  revealSecret(orgId: string, id: string): Observable<SecretOut> {
    return this.http.get<SecretOut>(`${this.org(orgId)}/endpoints/${id}/secret`);
  }
  createRoute(
    orgId: string,
    endpointId: string,
    body: { destination_id: string; transform_rule_id?: string | null },
  ): Observable<RouteInfo> {
    return this.http.post<RouteInfo>(`${this.org(orgId)}/endpoints/${endpointId}/routes`, body);
  }
  updateRoute(
    orgId: string,
    endpointId: string,
    routeId: string,
    body: { transform_rule_id?: string | null; clear_transform?: boolean; is_active?: boolean },
  ): Observable<RouteInfo> {
    return this.http.patch<RouteInfo>(
      `${this.org(orgId)}/endpoints/${endpointId}/routes/${routeId}`,
      body,
    );
  }
  deleteRoute(orgId: string, endpointId: string, routeId: string): Observable<void> {
    return this.http.delete<void>(`${this.org(orgId)}/endpoints/${endpointId}/routes/${routeId}`);
  }

  // ---------------------------------------------------------------- destinations
  destinations(orgId: string): Observable<Destination[]> {
    return this.http.get<Destination[]>(`${this.org(orgId)}/destinations`);
  }
  createDestination(orgId: string, body: Record<string, unknown>): Observable<Destination> {
    return this.http.post<Destination>(`${this.org(orgId)}/destinations`, body);
  }
  updateDestination(
    orgId: string,
    id: string,
    body: Record<string, unknown>,
  ): Observable<Destination> {
    return this.http.patch<Destination>(`${this.org(orgId)}/destinations/${id}`, body);
  }
  deleteDestination(orgId: string, id: string): Observable<void> {
    return this.http.delete<void>(`${this.org(orgId)}/destinations/${id}`);
  }

  // ---------------------------------------------------------------- transform rules
  rules(orgId: string): Observable<TransformRule[]> {
    return this.http.get<TransformRule[]>(`${this.org(orgId)}/transform-rules`);
  }
  rule(orgId: string, id: string): Observable<TransformRule> {
    return this.http.get<TransformRule>(`${this.org(orgId)}/transform-rules/${id}`);
  }
  createRule(orgId: string, body: Record<string, unknown>): Observable<TransformRule> {
    return this.http.post<TransformRule>(`${this.org(orgId)}/transform-rules`, body);
  }
  updateRule(orgId: string, id: string, body: Record<string, unknown>): Observable<TransformRule> {
    return this.http.patch<TransformRule>(`${this.org(orgId)}/transform-rules/${id}`, body);
  }
  deleteRule(orgId: string, id: string): Observable<void> {
    return this.http.delete<void>(`${this.org(orgId)}/transform-rules/${id}`);
  }
  previewRule(
    orgId: string,
    body: { mappings: Mapping[]; include_unmapped: boolean; sample_payload: unknown },
  ): Observable<PreviewResponse> {
    return this.http.post<PreviewResponse>(`${this.org(orgId)}/transform-rules/preview`, body);
  }

  // ---------------------------------------------------------------- events & deliveries
  events(orgId: string, query: QueryParams): Observable<Page<EventSummary>> {
    return this.http.get<Page<EventSummary>>(`${this.org(orgId)}/events`, {
      params: toParams(query),
    });
  }
  event(orgId: string, id: string): Observable<EventDetail> {
    return this.http.get<EventDetail>(`${this.org(orgId)}/events/${id}`);
  }
  replayEvent(orgId: string, id: string): Observable<ReplayResponse> {
    return this.http.post<ReplayResponse>(`${this.org(orgId)}/events/${id}/replay`, {});
  }
  deliveries(orgId: string, query: QueryParams): Observable<Page<DeliverySummary>> {
    return this.http.get<Page<DeliverySummary>>(`${this.org(orgId)}/deliveries`, {
      params: toParams(query),
    });
  }
  delivery(orgId: string, id: string): Observable<DeliveryDetail> {
    return this.http.get<DeliveryDetail>(`${this.org(orgId)}/deliveries/${id}`);
  }
  replayDelivery(orgId: string, id: string): Observable<ReplayResponse> {
    return this.http.post<ReplayResponse>(`${this.org(orgId)}/deliveries/${id}/replay`, {});
  }
  dashboard(orgId: string, hours: number): Observable<DashboardSummary> {
    return this.http.get<DashboardSummary>(`${this.org(orgId)}/dashboard/summary`, {
      params: toParams({ hours }),
    });
  }
}
