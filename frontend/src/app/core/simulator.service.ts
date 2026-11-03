import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { SimulatorControl, SimulatorRequests } from './models';

/** Talks to the failure simulator through the same-origin `/sim-api` reverse proxy. */
@Injectable({ providedIn: 'root' })
export class SimulatorService {
  private readonly http = inject(HttpClient);
  private readonly base = '/sim-api';

  control(): Observable<SimulatorControl> {
    return this.http.get<SimulatorControl>(`${this.base}/control`);
  }
  setControl(body: Partial<SimulatorControl>): Observable<SimulatorControl> {
    return this.http.put<SimulatorControl>(`${this.base}/control`, body);
  }
  reset(): Observable<SimulatorControl> {
    return this.http.post<SimulatorControl>(`${this.base}/control/reset`, {});
  }
  requests(limit = 50): Observable<SimulatorRequests> {
    return this.http.get<SimulatorRequests>(`${this.base}/requests`, { params: { limit } });
  }
  clear(): Observable<unknown> {
    return this.http.delete(`${this.base}/requests`);
  }
}
