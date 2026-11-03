import { Routes } from '@angular/router';

import { adminGuard, authGuard, guestGuard } from './core/guards';
import { ShellComponent } from './layout/shell.component';

export const routes: Routes = [
  {
    path: 'login',
    canActivate: [guestGuard],
    loadComponent: () => import('./features/auth/login.component').then((m) => m.LoginComponent),
    title: 'Entrar · ConnectHub',
  },
  {
    path: 'register',
    canActivate: [guestGuard],
    loadComponent: () =>
      import('./features/auth/register.component').then((m) => m.RegisterComponent),
    title: 'Criar conta · ConnectHub',
  },
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      {
        path: 'dashboard',
        loadComponent: () =>
          import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent),
        title: 'Dashboard · ConnectHub',
      },
      {
        path: 'endpoints',
        loadComponent: () =>
          import('./features/endpoints/endpoints.component').then((m) => m.EndpointsComponent),
        title: 'Endpoints · ConnectHub',
      },
      {
        path: 'endpoints/:id',
        loadComponent: () =>
          import('./features/endpoints/endpoint-detail.component').then(
            (m) => m.EndpointDetailComponent,
          ),
        title: 'Endpoint · ConnectHub',
      },
      {
        path: 'destinations',
        loadComponent: () =>
          import('./features/destinations/destinations.component').then(
            (m) => m.DestinationsComponent,
          ),
        title: 'Destinos · ConnectHub',
      },
      {
        path: 'transforms',
        loadComponent: () =>
          import('./features/transforms/transforms.component').then((m) => m.TransformsComponent),
        title: 'Transformações · ConnectHub',
      },
      {
        path: 'transforms/new',
        canActivate: [adminGuard],
        loadComponent: () =>
          import('./features/transforms/transform-editor.component').then(
            (m) => m.TransformEditorComponent,
          ),
        title: 'Nova transformação · ConnectHub',
      },
      {
        path: 'transforms/:id',
        loadComponent: () =>
          import('./features/transforms/transform-editor.component').then(
            (m) => m.TransformEditorComponent,
          ),
        title: 'Transformação · ConnectHub',
      },
      {
        path: 'events',
        loadComponent: () =>
          import('./features/events/events.component').then((m) => m.EventsComponent),
        title: 'Eventos · ConnectHub',
      },
      {
        path: 'events/:id',
        loadComponent: () =>
          import('./features/events/event-detail.component').then((m) => m.EventDetailComponent),
        title: 'Evento · ConnectHub',
      },
      {
        path: 'deliveries',
        loadComponent: () =>
          import('./features/deliveries/deliveries.component').then((m) => m.DeliveriesComponent),
        title: 'Entregas · ConnectHub',
      },
      {
        path: 'deliveries/:id',
        loadComponent: () =>
          import('./features/deliveries/delivery-detail.component').then(
            (m) => m.DeliveryDetailComponent,
          ),
        title: 'Entrega · ConnectHub',
      },
      {
        path: 'failures',
        loadComponent: () =>
          import('./features/failures/failures.component').then((m) => m.FailuresComponent),
        title: 'Falhas · ConnectHub',
      },
      {
        path: 'simulator',
        loadComponent: () =>
          import('./features/simulator/simulator.component').then((m) => m.SimulatorComponent),
        title: 'Simulador · ConnectHub',
      },
      {
        path: 'organization',
        loadComponent: () =>
          import('./features/orgs/organization.component').then((m) => m.OrganizationComponent),
        title: 'Organização · ConnectHub',
      },
      {
        path: 'settings',
        loadComponent: () =>
          import('./features/settings/settings.component').then((m) => m.SettingsComponent),
        title: 'Configurações · ConnectHub',
      },
    ],
  },
  { path: '**', redirectTo: 'dashboard' },
];
