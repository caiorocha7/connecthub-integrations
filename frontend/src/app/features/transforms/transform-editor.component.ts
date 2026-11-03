import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { debounceTime } from 'rxjs';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { Mapping, MappingTransform, MappingType, PreviewResponse } from '../../core/models';
import { ToastService } from '../../core/toast.service';
import { SHARED_UI } from '../../shared/ui';

const PATH = /^(\$\.)?[A-Za-z0-9_-]+(\[\d+\])*(\.[A-Za-z0-9_-]+(\[\d+\])*)*$/;

const DEFAULT_SAMPLE = {
  id: 'ord_1001',
  type: 'order.paid',
  data: {
    customer: { name: 'Maria Silva', email: 'MARIA@EXAMPLE.COM' },
    total: '259.90',
    currency: 'BRL',
    items: [{ sku: 'CH-001', qty: '2' }],
    paid_at: '2026-01-15T14:32:00Z',
  },
};

interface MappingFormValue {
  target: string;
  mode: 'source' | 'value';
  source: string;
  value: string;
  default: string;
  type: MappingType;
  transform: MappingTransform | '';
  required: boolean;
}

/** Parses a free-text constant/default: JSON literals when possible, otherwise the raw string. */
function parseLiteral(text: string): unknown {
  if (text === '') return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function literalToText(value: unknown): string {
  if (value === undefined || value === null) return '';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

@Component({
  selector: 'ch-transform-editor',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink, ...SHARED_UI],
  template: `
    <div class="page">
      <div class="breadcrumb">
        <a routerLink="/transforms">Transformações</a> /
        {{ isNew() ? 'Nova regra' : form.controls.name.value }}
      </div>
      <div class="page-header">
        <div>
          <h1>{{ isNew() ? 'Nova regra de transformação' : 'Editar regra' }}</h1>
          <p class="subtitle">
            Monte o JSON de saída campo a campo e valide com um payload de exemplo.
          </p>
        </div>
        <div class="actions">
          <button class="btn" (click)="runPreview()">
            <ch-icon name="play" [size]="14" /> Pré-visualizar
          </button>
          @if (auth.isAdmin()) {
            <button class="btn primary" (click)="save()" [disabled]="saving()">
              <ch-icon name="check" [size]="15" /> Salvar regra
            </button>
          }
        </div>
      </div>

      <form [formGroup]="form" novalidate>
        <div class="grid grid-half">
          <div class="stack">
            <div class="card">
              <div class="card-body">
                <div class="form-grid">
                  <div class="field">
                    <label for="r-name">Nome</label>
                    <input
                      id="r-name"
                      class="input"
                      formControlName="name"
                      placeholder="Ex.: Pedido → ERP"
                    />
                    @if (form.controls.name.touched && form.controls.name.invalid) {
                      <span class="error">Informe um nome.</span>
                    }
                  </div>
                  <div class="field">
                    <label for="r-desc">Descrição</label>
                    <input id="r-desc" class="input" formControlName="description" />
                  </div>
                </div>
                <label class="checkbox"
                  ><input type="checkbox" formControlName="include_unmapped" /> Incluir campos não
                  mapeados (copia o payload original e sobrescreve os mapeados)</label
                >
              </div>
            </div>

            <div class="card">
              <div class="card-header">
                <h2>Mapeamentos</h2>
                <button type="button" class="btn sm" (click)="addMapping()">
                  <ch-icon name="plus" [size]="14" /> Campo
                </button>
              </div>
              <div formArrayName="mappings">
                @if (mappings.length === 0) {
                  <p class="faint small" style="padding:16px 20px;margin:0">
                    Sem mapeamentos, o payload é repassado sem alterações.
                  </p>
                }
                @for (m of mappings.controls; track $index; let i = $index) {
                  <div class="mapping" [formGroupName]="i">
                    <div class="mapping-head">
                      <span class="idx">{{ i + 1 }}</span>
                      <select
                        class="input sm"
                        formControlName="mode"
                        style="width:auto"
                        aria-label="Tipo de origem"
                      >
                        <option value="source">Caminho</option>
                        <option value="value">Constante</option>
                      </select>
                      @if (m.value.mode === 'source') {
                        <input
                          class="input sm mono"
                          formControlName="source"
                          placeholder="data.customer.email"
                          aria-label="Caminho de origem"
                        />
                      } @else {
                        <input
                          class="input sm mono"
                          formControlName="value"
                          placeholder='"texto" ou 123 ou true'
                          aria-label="Valor constante"
                        />
                      }
                      <ch-icon name="arrow" [size]="14" />
                      <input
                        class="input sm mono"
                        formControlName="target"
                        placeholder="customer.email"
                        aria-label="Campo de destino"
                      />
                      <button
                        type="button"
                        class="btn sm ghost icon danger"
                        (click)="mappings.removeAt(i)"
                        aria-label="Remover"
                      >
                        <ch-icon name="x" [size]="14" />
                      </button>
                    </div>
                    <div class="mapping-opts">
                      <select class="input sm" formControlName="type" aria-label="Conversão">
                        <option value="keep">Manter tipo</option>
                        <option value="string">Texto</option>
                        <option value="integer">Inteiro</option>
                        <option value="float">Decimal</option>
                        <option value="boolean">Booleano</option>
                        <option value="datetime">Data/hora ISO</option>
                      </select>
                      <select
                        class="input sm"
                        formControlName="transform"
                        aria-label="Operação de texto"
                      >
                        <option value="">Sem operação</option>
                        <option value="trim">Remover espaços</option>
                        <option value="lower">minúsculas</option>
                        <option value="upper">MAIÚSCULAS</option>
                      </select>
                      @if (m.value.mode === 'source') {
                        <input
                          class="input sm mono"
                          formControlName="default"
                          placeholder="valor padrão"
                          aria-label="Valor padrão"
                        />
                        <label class="checkbox small"
                          ><input type="checkbox" formControlName="required" /> obrigatório</label
                        >
                      }
                    </div>
                    @if (
                      (m.controls['target'].touched && m.controls['target'].invalid) ||
                      (m.controls['source'].touched && m.controls['source'].invalid)
                    ) {
                      <div class="error small" style="padding-left:34px">
                        Caminhos aceitam letras, números, _ e -, separados por ponto, com índices
                        como items[0].
                      </div>
                    }
                  </div>
                }
              </div>
            </div>
          </div>

          <div class="stack">
            <div class="card">
              <div class="card-header">
                <h2>Payload de exemplo</h2>
                <span class="hint">JSON</span>
              </div>
              <div class="card-body">
                <textarea
                  class="input"
                  rows="14"
                  formControlName="sample"
                  aria-label="Payload de exemplo"
                ></textarea>
                @if (sampleError()) {
                  <div class="error small mt-1">{{ sampleError() }}</div>
                }
              </div>
            </div>
            <div class="card">
              <div class="card-header">
                <h2>Resultado</h2>
                @if (preview(); as p) {
                  <span class="badge" [class.success]="p.valid" [class.danger]="!p.valid">{{
                    p.valid ? 'Válido' : 'Inválido'
                  }}</span>
                }
              </div>
              <div class="card-body">
                @if (preview(); as p) {
                  @if (p.valid) {
                    <ch-json [value]="p.output" />
                  } @else {
                    <ul class="errors">
                      @for (e of p.errors; track $index) {
                        <li>{{ e }}</li>
                      }
                    </ul>
                  }
                } @else {
                  <p class="faint small" style="margin:0">
                    A pré-visualização é atualizada automaticamente enquanto você edita.
                  </p>
                }
              </div>
            </div>
          </div>
        </div>
      </form>
    </div>
  `,
  styles: [
    `
      .mapping {
        padding: 12px 20px;
        border-bottom: 1px solid var(--ch-border);
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .mapping:last-child {
        border-bottom: none;
      }
      .mapping-head,
      .mapping-opts {
        display: flex;
        gap: 8px;
        align-items: center;
      }
      .mapping-head input {
        flex: 1;
        min-width: 0;
      }
      .mapping-opts {
        padding-left: 34px;
        flex-wrap: wrap;
      }
      .mapping-opts select,
      .mapping-opts input:not([type="checkbox"]) {
        width: auto;
        min-width: 120px;
        flex: 1;
      }
      .idx {
        width: 24px;
        height: 24px;
        border-radius: 6px;
        background: var(--ch-primary-50);
        color: var(--ch-primary);
        display: grid;
        place-items: center;
        font-size: 11px;
        font-weight: 700;
        flex-shrink: 0;
      }
      .errors {
        margin: 0;
        padding-left: 18px;
        color: var(--ch-danger);
      }
    `,
  ],
})
export class TransformEditorComponent implements OnInit {
  readonly id = input<string>();
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  readonly isNew = signal(true);
  readonly saving = signal(false);
  readonly preview = signal<PreviewResponse | null>(null);
  readonly sampleError = signal<string | null>(null);

  readonly form = this.fb.nonNullable.group({
    name: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(120)]],
    description: [''],
    include_unmapped: [false],
    sample: [JSON.stringify(DEFAULT_SAMPLE, null, 2)],
    mappings: this.fb.array<FormGroup>([]),
  });

  get mappings(): FormArray<FormGroup> {
    return this.form.controls.mappings;
  }

  ngOnInit(): void {
    const id = this.id();
    if (id && id !== 'new') {
      this.isNew.set(false);
      this.api.rule(this.auth.orgId(), id).subscribe({
        next: (rule) => {
          this.form.patchValue({
            name: rule.name,
            description: rule.description ?? '',
            include_unmapped: rule.include_unmapped,
            sample: JSON.stringify(rule.sample_payload ?? DEFAULT_SAMPLE, null, 2),
          });
          rule.mappings.forEach((m) => this.addMapping(m));
          if (!this.auth.isAdmin()) this.form.disable({ emitEvent: false });
          this.runPreview();
        },
        error: (err: unknown) => {
          this.toast.error(err);
          void this.router.navigate(['/transforms']);
        },
      });
    } else {
      this.addMapping({ target: 'order_id', source: 'id', required: true });
      this.addMapping({
        target: 'customer.email',
        source: 'data.customer.email',
        type: 'string',
        transform: 'lower',
      });
      this.addMapping({ target: 'amount', source: 'data.total', type: 'float' });
      this.runPreview();
    }
    this.form.valueChanges
      .pipe(debounceTime(400), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.runPreview());
  }

  addMapping(m?: Mapping): void {
    const hasValue = m !== undefined && !m.source && m.value !== undefined && m.value !== null;
    const group = this.fb.nonNullable.group({
      target: [m?.target ?? '', [Validators.required, Validators.pattern(PATH)]],
      mode: [(hasValue ? 'value' : 'source') as 'source' | 'value'],
      source: [m?.source ?? '', [Validators.pattern(PATH)]],
      value: [hasValue ? literalToText(m?.value) : ''],
      default: [literalToText(m?.default)],
      type: [(m?.type ?? 'keep') as MappingType],
      transform: [(m?.transform ?? '') as MappingTransform | ''],
      required: [m?.required ?? false],
    });
    this.mappings.push(group);
  }

  private buildMappings(): Mapping[] {
    return (this.mappings.getRawValue() as MappingFormValue[]).map((m) => {
      const out: Mapping = { target: m.target.trim(), type: m.type };
      if (m.mode === 'source') {
        out.source = m.source.trim();
        const def = parseLiteral(m.default);
        if (def !== undefined) out.default = def;
        out.required = m.required;
      } else {
        out.value = parseLiteral(m.value) ?? '';
      }
      if (m.transform) out.transform = m.transform;
      return out;
    });
  }

  private parseSample(): unknown | undefined {
    try {
      const value = JSON.parse(this.form.controls.sample.value || '{}');
      this.sampleError.set(null);
      return value;
    } catch {
      this.sampleError.set('JSON de exemplo inválido.');
      return undefined;
    }
  }

  runPreview(): void {
    const sample = this.parseSample();
    if (sample === undefined) return;
    this.api
      .previewRule(this.auth.orgId(), {
        mappings: this.buildMappings(),
        include_unmapped: this.form.controls.include_unmapped.value,
        sample_payload: sample,
      })
      .subscribe({
        next: (p) => this.preview.set(p),
        error: (err: unknown) =>
          this.preview.set({ valid: false, output: null, errors: [this.describe(err)] }),
      });
  }

  private describe(err: unknown): string {
    const e = err as { error?: { errors?: { field: string; message: string }[]; detail?: string } };
    return (
      e.error?.errors?.map((x) => `${x.field}: ${x.message}`).join(' · ') ??
      e.error?.detail ??
      'Regra inválida'
    );
  }

  save(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.toast.show('error', 'Corrija os campos destacados antes de salvar.');
      return;
    }
    const sample = this.parseSample();
    const body = {
      name: this.form.controls.name.value,
      description: this.form.controls.description.value || null,
      include_unmapped: this.form.controls.include_unmapped.value,
      mappings: this.buildMappings(),
      sample_payload:
        sample && typeof sample === 'object' && !Array.isArray(sample) ? sample : null,
    };
    const id = this.id();
    const req =
      this.isNew() || !id
        ? this.api.createRule(this.auth.orgId(), body)
        : this.api.updateRule(this.auth.orgId(), id, body);
    this.saving.set(true);
    req.subscribe({
      next: (rule) => {
        this.saving.set(false);
        this.toast.success('Regra salva.');
        if (this.isNew()) void this.router.navigate(['/transforms', rule.id]);
      },
      error: (err: unknown) => {
        this.saving.set(false);
        this.toast.error(err);
      },
    });
  }
}
