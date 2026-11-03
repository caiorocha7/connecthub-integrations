import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { DonutChartComponent, LineChartComponent } from './charts';
import { HttpCodeComponent, PaginationComponent, StatusBadgeComponent } from './ui';

describe('shared UI components', () => {
  it('renders a status badge with label and tone', async () => {
    const fixture = TestBed.createComponent(StatusBadgeComponent);
    fixture.componentRef.setInput('status', 'RETRYING');
    await fixture.whenStable();
    const el: HTMLElement = fixture.nativeElement.querySelector('.badge');
    expect(el.textContent?.trim()).toBe('Retentando');
    expect(el.classList).toContain('warning');
    expect(el.classList).toContain('pulse');
  });

  it('colors HTTP codes', async () => {
    const fixture = TestBed.createComponent(HttpCodeComponent);
    fixture.componentRef.setInput('code', 503);
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('.badge').classList).toContain('warning');
    fixture.componentRef.setInput('code', 201);
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('.badge').classList).toContain('success');
  });

  it('paginates and emits page changes', async () => {
    const fixture = TestBed.createComponent(PaginationComponent);
    fixture.componentRef.setInput('page', 1);
    fixture.componentRef.setInput('pages', 3);
    fixture.componentRef.setInput('total', 45);
    fixture.componentRef.setInput('pageSize', 20);
    const pages: number[] = [];
    fixture.componentInstance.pageChange.subscribe((p) => pages.push(p));
    await fixture.whenStable();
    expect(fixture.nativeElement.textContent).toContain('1–20 de 45');
    const [prev, next] = fixture.nativeElement.querySelectorAll('button');
    expect(prev.disabled).toBe(true);
    next.click();
    expect(pages).toEqual([2]);
  });

  it('draws one path per chart series', async () => {
    const fixture = TestBed.createComponent(LineChartComponent);
    fixture.componentRef.setInput('labels', ['00h', '01h', '02h']);
    fixture.componentRef.setInput('series', [
      { label: 'Recebidos', color: '#000', values: [1, 4, 2] },
      { label: 'Falhas', color: '#f00', values: [0, 1, 0] },
    ]);
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelectorAll('circle').length).toBe(6);
    expect(fixture.nativeElement.textContent).toContain('Recebidos');
  });

  it('builds donut arcs only for non-zero slices', async () => {
    const fixture = TestBed.createComponent(DonutChartComponent);
    fixture.componentRef.setInput('slices', [
      { label: 'Sucesso', value: 3, color: 'green' },
      { label: 'Falha', value: 0, color: 'red' },
    ]);
    await fixture.whenStable();
    expect(fixture.componentInstance.arcs().length).toBe(1);
  });
});
