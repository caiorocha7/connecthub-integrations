import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export interface ChartSeries {
  label: string;
  color: string;
  values: number[];
}

const W = 640;
const H = 220;
const PAD = { top: 16, right: 12, bottom: 28, left: 36 };

/** Lightweight responsive SVG line/area chart (no third-party chart dependency). */
@Component({
  selector: 'ch-line-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="legend">
      @for (s of series(); track s.label) {
        <span class="legend-item"><i [style.background]="s.color"></i>{{ s.label }}</span>
      }
    </div>
    <svg
      [attr.viewBox]="'0 0 ' + w + ' ' + h"
      class="chart"
      role="img"
      [attr.aria-label]="ariaLabel()"
    >
      @for (t of ticks(); track t.value) {
        <line
          [attr.x1]="pad.left"
          [attr.x2]="w - pad.right"
          [attr.y1]="t.y"
          [attr.y2]="t.y"
          class="grid"
        />
        <text [attr.x]="pad.left - 8" [attr.y]="t.y + 4" class="axis" text-anchor="end">
          {{ t.value }}
        </text>
      }
      @for (l of xLabels(); track l.i) {
        <text [attr.x]="l.x" [attr.y]="h - 8" class="axis" text-anchor="middle">{{ l.text }}</text>
      }
      @for (p of paths(); track p.label) {
        <path [attr.d]="p.area" [attr.fill]="p.color" opacity="0.08" />
        <path
          [attr.d]="p.line"
          [attr.stroke]="p.color"
          fill="none"
          stroke-width="2.2"
          stroke-linejoin="round"
        />
        @for (pt of p.points; track $index) {
          <circle [attr.cx]="pt.x" [attr.cy]="pt.y" r="2.6" [attr.fill]="p.color">
            <title>{{ p.label }} · {{ pt.label }}: {{ pt.v }}</title>
          </circle>
        }
      }
    </svg>
  `,
  styles: [
    `
      :host {
        display: block;
      }
      .chart {
        width: 100%;
        height: auto;
        display: block;
      }
      .grid {
        stroke: var(--ch-border);
        stroke-dasharray: 3 4;
      }
      .axis {
        fill: var(--ch-text-3);
        font-size: 10px;
        font-family: var(--ch-font);
      }
      .legend {
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
        margin-bottom: 8px;
        font-size: 12.5px;
        color: var(--ch-text-2);
      }
      .legend-item {
        display: inline-flex;
        align-items: center;
        gap: 6px;
      }
      .legend-item i {
        width: 10px;
        height: 10px;
        border-radius: 3px;
        display: inline-block;
      }
    `,
  ],
})
export class LineChartComponent {
  readonly series = input.required<ChartSeries[]>();
  readonly labels = input.required<string[]>();
  readonly ariaLabel = input('gráfico');
  readonly w = W;
  readonly h = H;
  readonly pad = PAD;

  private readonly max = computed(() => {
    const all = this.series().flatMap((s) => s.values);
    const m = Math.max(1, ...all);
    const magnitude = Math.pow(10, Math.floor(Math.log10(m)));
    return Math.ceil(m / magnitude) * magnitude;
  });

  readonly ticks = computed(() => {
    const max = this.max();
    return [0, 0.25, 0.5, 0.75, 1].map((f) => ({ value: Math.round(max * f), y: this.y(max * f) }));
  });

  readonly xLabels = computed(() => {
    const labels = this.labels();
    const n = labels.length;
    const every = Math.max(1, Math.ceil(n / 8));
    return labels
      .map((text, i) => ({ text, i, x: this.x(i, n) }))
      .filter((l) => l.i % every === 0 || l.i === n - 1);
  });

  readonly paths = computed(() => {
    const labels = this.labels();
    const n = labels.length;
    return this.series().map((s) => {
      const points = s.values.map((v, i) => ({
        x: this.x(i, n),
        y: this.y(v),
        v,
        label: labels[i] ?? '',
      }));
      const line = points
        .map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
        .join(' ');
      const base = this.y(0);
      const area = points.length
        ? `${line} L${points[points.length - 1].x.toFixed(1)},${base} L${points[0].x.toFixed(1)},${base} Z`
        : '';
      return { label: s.label, color: s.color, line, area, points };
    });
  });

  private x(i: number, n: number): number {
    const span = W - PAD.left - PAD.right;
    return PAD.left + (n <= 1 ? span / 2 : (span * i) / (n - 1));
  }

  private y(v: number): number {
    const span = H - PAD.top - PAD.bottom;
    return PAD.top + span - (span * v) / this.max();
  }
}

export interface DonutSlice {
  label: string;
  value: number;
  color: string;
}

@Component({
  selector: 'ch-donut',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="donut-wrap">
      <svg viewBox="0 0 120 120" class="donut" role="img" [attr.aria-label]="centerLabel()">
        <circle
          cx="60"
          cy="60"
          r="46"
          fill="none"
          stroke="var(--ch-neutral-50)"
          stroke-width="14"
        />
        @for (a of arcs(); track a.label) {
          <circle
            cx="60"
            cy="60"
            r="46"
            fill="none"
            [attr.stroke]="a.color"
            stroke-width="14"
            [attr.stroke-dasharray]="a.dash"
            [attr.stroke-dashoffset]="a.offset"
            transform="rotate(-90 60 60)"
          >
            <title>{{ a.label }}: {{ a.value }}</title>
          </circle>
        }
        <text x="60" y="58" text-anchor="middle" class="center-value">{{ centerValue() }}</text>
        <text x="60" y="74" text-anchor="middle" class="center-label">{{ centerLabel() }}</text>
      </svg>
      <ul class="legend">
        @for (s of slices(); track s.label) {
          <li>
            <i [style.background]="s.color"></i><span>{{ s.label }}</span
            ><b>{{ s.value }}</b>
          </li>
        }
      </ul>
    </div>
  `,
  styles: [
    `
      .donut-wrap {
        display: flex;
        align-items: center;
        gap: 20px;
        flex-wrap: wrap;
        justify-content: center;
      }
      .donut {
        width: 150px;
        height: 150px;
      }
      .center-value {
        font-size: 20px;
        font-weight: 700;
        fill: var(--ch-text);
        font-family: var(--ch-font);
      }
      .center-label {
        font-size: 8px;
        fill: var(--ch-text-3);
        font-family: var(--ch-font);
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }
      .legend {
        list-style: none;
        padding: 0;
        margin: 0;
        display: flex;
        flex-direction: column;
        gap: 8px;
        min-width: 150px;
      }
      .legend li {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 13px;
        color: var(--ch-text-2);
      }
      .legend i {
        width: 10px;
        height: 10px;
        border-radius: 3px;
      }
      .legend b {
        margin-left: auto;
        color: var(--ch-text);
      }
    `,
  ],
})
export class DonutChartComponent {
  readonly slices = input.required<DonutSlice[]>();
  readonly centerValue = input<string>('');
  readonly centerLabel = input<string>('');

  readonly arcs = computed(() => {
    const total = this.slices().reduce((acc, s) => acc + s.value, 0);
    const circumference = 2 * Math.PI * 46;
    let offset = 0;
    return this.slices()
      .filter((s) => s.value > 0 && total > 0)
      .map((s) => {
        const len = (s.value / total) * circumference;
        const arc = { ...s, dash: `${len} ${circumference - len}`, offset: -offset };
        offset += len;
        return arc;
      });
  });
}
