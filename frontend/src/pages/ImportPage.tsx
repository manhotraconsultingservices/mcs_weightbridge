import { useState, useRef } from 'react';
import { Upload, Download, CheckCircle, XCircle, AlertCircle, Users, Package, Truck, Loader2, FileSpreadsheet } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import api from '@/services/api';

type Entity = 'parties' | 'products' | 'vehicles';

interface PreviewResult {
  entity: string;
  total_rows: number;
  columns: string[];
  preview: Record<string, string>[];
}

interface ImportResult {
  entity: string;
  created: number;
  updated: number;
  skipped: number;
  errors: string[];
}

const ENTITY_CONFIG: Record<Entity, {
  label: string;
  icon: React.ElementType;
  description: string;
  required: string[];
  optional: string[];
  color: string;
}> = {
  parties: {
    label: 'Parties',
    icon: Users,
    description: 'Import customers and suppliers with GSTIN, phone, address details.',
    required: ['name', 'party_type'],
    optional: ['gstin', 'pan', 'phone', 'email', 'billing_address', 'billing_city', 'billing_state', 'credit_limit', 'payment_terms_days'],
    color: 'text-blue-600',
  },
  products: {
    label: 'Products',
    icon: Package,
    description: 'Import product catalog with HSN codes, rates, and GST rates.',
    required: ['name'],
    optional: ['category', 'hsn_code', 'unit', 'default_rate', 'gst_rate', 'code', 'description'],
    color: 'text-green-600',
  },
  vehicles: {
    label: 'Vehicles',
    icon: Truck,
    description: 'Import vehicle registrations with owner and tare weight details.',
    required: ['registration_no'],
    optional: ['vehicle_type', 'owner_name', 'owner_phone', 'default_tare_weight'],
    color: 'text-purple-600',
  },
};

function ImportPanel({ entity }: { entity: Entity }) {
  const cfg = ENTITY_CONFIG[entity];
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [updateExisting, setUpdateExisting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState('');

  async function handleFileChange(f: File) {
    setFile(f);
    setPreview(null);
    setResult(null);
    setError('');

    // Auto-preview
    setPreviewing(true);
    try {
      const fd = new FormData();
      fd.append('file', f);
      const { data } = await api.post<PreviewResult>(`/api/v1/import/preview/${entity}`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setPreview(data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to preview file');
    } finally { setPreviewing(false); }
  }

  async function doImport() {
    if (!file) return;
    setImporting(true); setResult(null); setError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('update_existing', String(updateExisting));
      const { data } = await api.post<ImportResult>(`/api/v1/import/${entity}`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setResult(data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Import failed');
    } finally { setImporting(false); }
  }

  async function downloadTemplate() {
    try {
      const res = await api.get(`/api/v1/import/template/${entity}`, { responseType: 'blob' });
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${entity}_template.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { /* ignore */ }
  }

  const Icon = cfg.icon;

  return (
    <div className="space-y-4">
      {/* Info */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex items-start gap-3">
            <Icon className={`h-5 w-5 ${cfg.color} mt-0.5 shrink-0`} />
            <div className="flex-1 space-y-2">
              <p className="text-sm">{cfg.description}</p>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                <div>
                  <span className="font-medium text-destructive">Required: </span>
                  {cfg.required.map(c => <code key={c} className="bg-muted px-1 rounded mr-1">{c}</code>)}
                </div>
                <div>
                  <span className="font-medium text-muted-foreground">Optional: </span>
                  {cfg.optional.map(c => <code key={c} className="bg-muted px-1 rounded mr-1">{c}</code>)}
                </div>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={downloadTemplate}>
              <Download className="mr-1.5 h-4 w-4" /> Template
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* File picker */}
      <Card>
        <CardContent className="pt-4 space-y-4">
          <div
            className="border-2 border-dashed rounded-lg p-8 text-center cursor-pointer hover:border-primary/50 transition-colors"
            onClick={() => fileRef.current?.click()}
            onDragOver={e => e.preventDefault()}
            onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleFileChange(f); }}
          >
            <FileSpreadsheet className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
            <p className="text-sm font-medium">{file ? file.name : 'Drop Excel / CSV file here'}</p>
            <p className="text-xs text-muted-foreground mt-1">
              {file ? `${(file.size / 1024).toFixed(1)} KB` : 'or click to browse (.xlsx, .xls, .csv)'}
            </p>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) handleFileChange(f); }}
          />

          {/* Update existing toggle */}
          <label className="flex items-center gap-2 cursor-pointer text-sm">
            <input
              type="checkbox"
              checked={updateExisting}
              onChange={e => setUpdateExisting(e.target.checked)}
              className="h-4 w-4 rounded border-gray-300"
            />
            <span>Update existing records (if name / registration already exists)</span>
          </label>
        </CardContent>
      </Card>

      {/* Preview loading */}
      {previewing && (
        <Card>
          <CardContent className="py-6 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Reading file...
          </CardContent>
        </Card>
      )}

      {/* Preview table */}
      {preview && !previewing && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center justify-between">
              <span>Preview — {preview.total_rows} rows detected</span>
              <Button onClick={doImport} disabled={importing}>
                {importing
                  ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Importing...</>
                  : <><Upload className="mr-2 h-4 w-4" /> Import {preview.total_rows} Rows</>
                }
              </Button>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-muted/50">
                    {preview.columns.map(col => (
                      <th key={col} className="px-3 py-2 text-left font-medium text-muted-foreground">
                        {col}
                        {cfg.required.includes(col) && <span className="text-destructive ml-1">*</span>}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {preview.preview.map((row, i) => (
                    <tr key={i} className="hover:bg-muted/30">
                      {preview.columns.map(col => (
                        <td key={col} className="px-3 py-2 max-w-[160px] truncate">
                          {String(row[col] ?? '')}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {preview.total_rows > 10 && (
                <p className="px-3 py-2 text-xs text-muted-foreground border-t">
                  Showing first 10 of {preview.total_rows} rows
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Result */}
      {result && (
        <Card className={result.errors.length > 0 ? 'border-amber-300 bg-amber-50/30' : 'border-green-300 bg-green-50/30'}>
          <CardContent className="pt-4 space-y-3">
            <div className="flex items-center gap-2">
              {result.errors.length === 0
                ? <CheckCircle className="h-5 w-5 text-green-600" />
                : <AlertCircle className="h-5 w-5 text-amber-600" />
              }
              <span className="font-medium text-sm">
                Import complete for {result.entity}
              </span>
            </div>
            <div className="flex gap-4 text-sm">
              <span className="text-green-700 font-medium">+{result.created} created</span>
              <span className="text-blue-700 font-medium">{result.updated} updated</span>
              <span className="text-muted-foreground">{result.skipped} skipped</span>
            </div>
            {result.errors.length > 0 && (
              <div>
                <p className="text-xs font-medium text-amber-700 mb-1">Errors ({result.errors.length}):</p>
                <ul className="text-xs text-amber-800 space-y-0.5 max-h-32 overflow-y-auto">
                  {result.errors.map((err, i) => (
                    <li key={i} className="flex gap-1">
                      <XCircle className="h-3 w-3 shrink-0 mt-0.5" /> {err}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Error */}
      {error && (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardContent className="pt-4 flex items-start gap-2 text-sm text-destructive">
            <XCircle className="h-4 w-4 shrink-0 mt-0.5" /> {error}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function ImportPage() {
  const [tab, setTab] = useState<Entity>('parties');

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
          <Upload className="h-8 w-8 text-primary" /> Data Import
        </h1>
        <p className="text-muted-foreground">Bulk import parties, products, and vehicles from Excel or CSV files</p>
      </div>

      {/* How it works */}
      <Card className="bg-blue-50/40 border-blue-200">
        <CardContent className="pt-4">
          <div className="flex gap-3 text-sm text-blue-800">
            <div className="space-y-1">
              <p className="font-medium">How it works:</p>
              <ol className="list-decimal list-inside space-y-0.5 text-blue-700">
                <li>Download the blank Excel template for your entity type</li>
                <li>Fill in the data (see required * and optional columns)</li>
                <li>Upload the file — a preview of first 10 rows is shown</li>
                <li>Confirm and click Import</li>
              </ol>
            </div>
          </div>
        </CardContent>
      </Card>

      <Tabs value={tab} onValueChange={v => setTab(v as Entity)}>
        <TabsList>
          {(Object.keys(ENTITY_CONFIG) as Entity[]).map(e => {
            const cfg = ENTITY_CONFIG[e];
            const Icon = cfg.icon;
            return (
              <TabsTrigger key={e} value={e}>
                <Icon className="mr-1.5 h-4 w-4" />
                {cfg.label}
              </TabsTrigger>
            );
          })}
        </TabsList>

        {(Object.keys(ENTITY_CONFIG) as Entity[]).map(e => (
          <TabsContent key={e} value={e} className="mt-4">
            <ImportPanel entity={e} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
