import { useState } from 'react';
import { Search, FileJson } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import api from '@/services/api';
import { DataTable, type ColumnDef } from '@/components/DataTable';

const fmt = (n: number) => '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => { const d = new Date(); d.setDate(1); return d.toISOString().slice(0, 10); };

// ── GSTR-1 types ─────────────────────────────────────────────────────────────

interface GstRow { invoice_no: string; invoice_date: string; party_name: string; gstin: string | null; taxable_amount: number; cgst_amount: number; sgst_amount: number; igst_amount: number; grand_total: number; }
interface HsnRow { hsn_code: string; unit: string; quantity: number; taxable_amount: number; cgst_amount: number; sgst_amount: number; igst_amount: number; }
interface GstTotals { taxable: number; cgst: number; sgst: number; igst: number; total: number; }
interface Gstr1Data { b2b: GstRow[]; b2b_totals: GstTotals; b2c: GstRow[]; b2c_totals: GstTotals; hsn_summary: HsnRow[]; }

// ── GSTR-3B types ─────────────────────────────────────────────────────────────

interface TaxBlock { igst: number; cgst: number; sgst: number; cess: number; total?: number; total_tax?: number; }
interface Gstr3bData {
  gstin: string; period: string;
  section_3_1: {
    a_taxable_outward: TaxBlock & { description: string; invoice_count: number; taxable_value: number; };
    e_non_gst: { description: string; invoice_count: number; total_value: number; inter_state: number; intra_state: number; };
  };
  section_4: {
    a_itc_available: { all_other_itc: TaxBlock & { description: string; invoice_count: number; taxable_value: number; total_itc: number; }; };
    net_itc: TaxBlock & { total: number; };
  };
  net_tax_payable: TaxBlock & { total: number; };
}

// ── Shared components ─────────────────────────────────────────────────────────

function TaxCard({ label, igst, cgst, sgst, total }: { label: string; igst: number; cgst: number; sgst: number; total: number }) {
  return (
    <div className="rounded-lg border p-4 space-y-2">
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className="text-xl font-bold">{fmt(total)}</p>
      <div className="grid grid-cols-3 gap-1 text-xs text-muted-foreground">
        <span>CGST: {fmt(cgst)}</span>
        <span>SGST: {fmt(sgst)}</span>
        <span>IGST: {fmt(igst)}</span>
      </div>
    </div>
  );
}

// ── Column definitions ────────────────────────────────────────────────────────

const B2B_COLUMNS: ColumnDef<GstRow>[] = [
  {
    key: 'invoice_no',
    label: 'Invoice No',
    type: 'string',
    accessor: r => r.invoice_no,
    format: (v) => <span className="font-mono text-xs font-medium">{String(v ?? '')}</span>,
  },
  {
    key: 'invoice_date',
    label: 'Date',
    type: 'date',
    accessor: r => r.invoice_date,
    format: (v) => <span className="text-xs text-muted-foreground">{String(v ?? '')}</span>,
  },
  {
    key: 'party_name',
    label: 'Party',
    type: 'string',
    accessor: r => r.party_name,
  },
  {
    key: 'gstin',
    label: 'GSTIN',
    type: 'string',
    accessor: r => r.gstin ?? '',
    format: (v) => <span className="font-mono text-xs text-muted-foreground">{String(v ?? '')}</span>,
  },
  {
    key: 'taxable_amount',
    label: 'Taxable',
    type: 'number',
    align: 'right',
    accessor: r => r.taxable_amount,
    format: (v) => fmt(Number(v ?? 0)),
    exportValue: r => r.taxable_amount,
  },
  {
    key: 'cgst_amount',
    label: 'CGST',
    type: 'number',
    align: 'right',
    accessor: r => r.cgst_amount,
    format: (v) => fmt(Number(v ?? 0)),
    exportValue: r => r.cgst_amount,
  },
  {
    key: 'sgst_amount',
    label: 'SGST',
    type: 'number',
    align: 'right',
    accessor: r => r.sgst_amount,
    format: (v) => fmt(Number(v ?? 0)),
    exportValue: r => r.sgst_amount,
  },
  {
    key: 'igst_amount',
    label: 'IGST',
    type: 'number',
    align: 'right',
    accessor: r => r.igst_amount,
    format: (v) => fmt(Number(v ?? 0)),
    exportValue: r => r.igst_amount,
  },
  {
    key: 'grand_total',
    label: 'Total',
    type: 'number',
    align: 'right',
    accessor: r => r.grand_total,
    format: (v) => <span className="font-semibold">{fmt(Number(v ?? 0))}</span>,
    exportValue: r => r.grand_total,
  },
];

const B2C_COLUMNS: ColumnDef<GstRow>[] = [
  {
    key: 'invoice_no',
    label: 'Invoice No',
    type: 'string',
    accessor: r => r.invoice_no,
    format: (v) => <span className="font-mono text-xs font-medium">{String(v ?? '')}</span>,
  },
  {
    key: 'invoice_date',
    label: 'Date',
    type: 'date',
    accessor: r => r.invoice_date,
    format: (v) => <span className="text-xs text-muted-foreground">{String(v ?? '')}</span>,
  },
  {
    key: 'party_name',
    label: 'Party',
    type: 'string',
    accessor: r => r.party_name,
  },
  {
    key: 'taxable_amount',
    label: 'Taxable',
    type: 'number',
    align: 'right',
    accessor: r => r.taxable_amount,
    format: (v) => fmt(Number(v ?? 0)),
    exportValue: r => r.taxable_amount,
  },
  {
    key: 'cgst_amount',
    label: 'CGST',
    type: 'number',
    align: 'right',
    accessor: r => r.cgst_amount,
    format: (v) => fmt(Number(v ?? 0)),
    exportValue: r => r.cgst_amount,
  },
  {
    key: 'sgst_amount',
    label: 'SGST',
    type: 'number',
    align: 'right',
    accessor: r => r.sgst_amount,
    format: (v) => fmt(Number(v ?? 0)),
    exportValue: r => r.sgst_amount,
  },
  {
    key: 'igst_amount',
    label: 'IGST',
    type: 'number',
    align: 'right',
    accessor: r => r.igst_amount,
    format: (v) => fmt(Number(v ?? 0)),
    exportValue: r => r.igst_amount,
  },
  {
    key: 'grand_total',
    label: 'Total',
    type: 'number',
    align: 'right',
    accessor: r => r.grand_total,
    format: (v) => <span className="font-semibold">{fmt(Number(v ?? 0))}</span>,
    exportValue: r => r.grand_total,
  },
];

const HSN_COLUMNS: ColumnDef<HsnRow>[] = [
  {
    key: 'hsn_code',
    label: 'HSN Code',
    type: 'string',
    accessor: r => r.hsn_code,
    format: (v) => <span className="font-mono font-medium">{String(v ?? '')}</span>,
  },
  {
    key: 'unit',
    label: 'UQC',
    type: 'string',
    accessor: r => r.unit,
    format: (v) => <span className="text-muted-foreground">{String(v ?? '')}</span>,
  },
  {
    key: 'quantity',
    label: 'Quantity',
    type: 'number',
    align: 'right',
    accessor: r => r.quantity,
    format: (v) => Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 3 }),
    exportValue: r => r.quantity,
  },
  {
    key: 'taxable_amount',
    label: 'Taxable',
    type: 'number',
    align: 'right',
    accessor: r => r.taxable_amount,
    format: (v) => fmt(Number(v ?? 0)),
    exportValue: r => r.taxable_amount,
  },
  {
    key: 'cgst_amount',
    label: 'CGST',
    type: 'number',
    align: 'right',
    accessor: r => r.cgst_amount,
    format: (v) => fmt(Number(v ?? 0)),
    exportValue: r => r.cgst_amount,
  },
  {
    key: 'sgst_amount',
    label: 'SGST',
    type: 'number',
    align: 'right',
    accessor: r => r.sgst_amount,
    format: (v) => fmt(Number(v ?? 0)),
    exportValue: r => r.sgst_amount,
  },
  {
    key: 'igst_amount',
    label: 'IGST',
    type: 'number',
    align: 'right',
    accessor: r => r.igst_amount,
    format: (v) => fmt(Number(v ?? 0)),
    exportValue: r => r.igst_amount,
  },
];

// ── Totals summary strip (replaces the old TotalsRow inside <tbody>) ──────────

function TotalsSummary({ totals, count, label }: { totals: GstTotals; count: number; label: string }) {
  return (
    <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
      <span className="font-medium text-foreground">{label} ({count})</span>
      <span>Taxable: <span className="font-semibold text-foreground">{fmt(totals.taxable)}</span></span>
      <span>CGST: <span className="font-semibold text-foreground">{fmt(totals.cgst)}</span></span>
      <span>SGST: <span className="font-semibold text-foreground">{fmt(totals.sgst)}</span></span>
      <span>IGST: <span className="font-semibold text-foreground">{fmt(totals.igst)}</span></span>
      <span>Total: <span className="font-bold text-foreground">{fmt(totals.total)}</span></span>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function GstReportsPage() {
  const { t } = useTranslation();
  const [mainTab, setMainTab] = useState('gstr1');
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());

  // GSTR-1 state
  const [gstr1Data, setGstr1Data] = useState<Gstr1Data | null>(null);
  const [gstr1Loading, setGstr1Loading] = useState(false);
  const [gstr1Tab, setGstr1Tab] = useState('b2b');
  const [jsonDownloading, setJsonDownloading] = useState(false);

  // GSTR-3B state
  const [gstr3bData, setGstr3bData] = useState<Gstr3bData | null>(null);
  const [gstr3bLoading, setGstr3bLoading] = useState(false);

  async function fetchGstr1() {
    setGstr1Loading(true);
    const params = new URLSearchParams({ from_date: from, to_date: to });
    api.get<Gstr1Data>(`/api/v1/reports/gstr1?${params}`)
      .then(r => setGstr1Data(r.data))
      .catch(() => setGstr1Data(null))
      .finally(() => setGstr1Loading(false));
  }

  async function fetchGstr3b() {
    setGstr3bLoading(true);
    const params = new URLSearchParams({ from_date: from, to_date: to });
    api.get<Gstr3bData>(`/api/v1/reports/gstr3b?${params}`)
      .then(r => setGstr3bData(r.data))
      .catch(() => setGstr3bData(null))
      .finally(() => setGstr3bLoading(false));
  }

  async function downloadGstr1Json() {
    setJsonDownloading(true);
    try {
      const params = new URLSearchParams({ from_date: from, to_date: to });
      const res = await api.get(`/api/v1/reports/gstr1-json?${params}`, { responseType: 'blob' });
      const cd = res.headers['content-disposition'] || '';
      const match = cd.match(/filename=(.+)/);
      const filename = match ? match[1] : `GSTR1_${from}_${to}.json`;
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/json' }));
      const a = document.createElement('a'); a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    } finally {
      setJsonDownloading(false);
    }
  }

  const periodControls = (
    <div className="flex flex-wrap items-end gap-3">
      <div className="space-y-1">
        <Label className="text-xs">{t('common.from')}</Label>
        <Input type="date" className="w-36" value={from} onChange={e => setFrom(e.target.value)} />
      </div>
      <div className="space-y-1">
        <Label className="text-xs">{t('common.to')}</Label>
        <Input type="date" className="w-36" value={to} onChange={e => setTo(e.target.value)} />
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{t('gst.title')}</h1>
        <p className="text-muted-foreground">{t('gst.subtitle')}</p>
      </div>

      <Tabs value={mainTab} onValueChange={setMainTab}>
        <TabsList>
          <TabsTrigger value="gstr1">{t('reports.gstr1')}</TabsTrigger>
          <TabsTrigger value="gstr3b">{t('reports.gstr3b')}</TabsTrigger>
        </TabsList>

        {/* ── GSTR-1 ── */}
        <TabsContent value="gstr1" className="mt-4 space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            {periodControls}
            <Button onClick={fetchGstr1} disabled={gstr1Loading}>
              <Search className="mr-2 h-4 w-4" /> {gstr1Loading ? t('common.loading') : t('gst.generate')}
            </Button>
            <Button variant="outline" onClick={downloadGstr1Json} disabled={jsonDownloading}>
              <FileJson className="mr-2 h-4 w-4" /> {jsonDownloading ? t('gst.preparing') : t('gst.jsonExport')}
            </Button>
          </div>

          {gstr1Data && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">{t('gst.b2bInvoices')}</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{gstr1Data.b2b.length}</p></CardContent></Card>
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">{t('gst.b2cInvoices')}</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{gstr1Data.b2c.length}</p></CardContent></Card>
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">{t('gst.totalTaxB2b')}</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{fmt(gstr1Data.b2b_totals.cgst + gstr1Data.b2b_totals.sgst + gstr1Data.b2b_totals.igst)}</p></CardContent></Card>
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">{t('gst.totalTaxB2c')}</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{fmt(gstr1Data.b2c_totals.cgst + gstr1Data.b2c_totals.sgst + gstr1Data.b2c_totals.igst)}</p></CardContent></Card>
              </div>

              <Tabs value={gstr1Tab} onValueChange={setGstr1Tab}>
                <TabsList>
                  <TabsTrigger value="b2b">{t('gst.b2bTab')} ({gstr1Data.b2b.length})</TabsTrigger>
                  <TabsTrigger value="b2c">{t('gst.b2cTab')} ({gstr1Data.b2c.length})</TabsTrigger>
                  <TabsTrigger value="hsn">{t('gst.hsnSummary')}</TabsTrigger>
                </TabsList>

                <TabsContent value="b2b" className="mt-4">
                  <DataTable<GstRow>
                    id="gstr1.b2b"
                    data={gstr1Data.b2b}
                    columns={B2B_COLUMNS}
                    rowKey={(r, i) => `${r.invoice_no}-${i}`}
                    exportFilename={`gstr1-b2b-${from}-${to}`}
                    defaultSort={{ key: 'invoice_date', direction: 'desc' }}
                    emptyMessage={t('gst.noB2b')}
                    toolbarLeft={
                      gstr1Data.b2b.length > 0 ? (
                        <TotalsSummary
                          totals={gstr1Data.b2b_totals}
                          count={gstr1Data.b2b.length}
                          label="B2B Total"
                        />
                      ) : undefined
                    }
                  />
                </TabsContent>

                <TabsContent value="b2c" className="mt-4">
                  <DataTable<GstRow>
                    id="gstr1.b2c"
                    data={gstr1Data.b2c}
                    columns={B2C_COLUMNS}
                    rowKey={(r, i) => `${r.invoice_no}-${i}`}
                    exportFilename={`gstr1-b2c-${from}-${to}`}
                    defaultSort={{ key: 'invoice_date', direction: 'desc' }}
                    emptyMessage={t('gst.noB2c')}
                    toolbarLeft={
                      gstr1Data.b2c.length > 0 ? (
                        <TotalsSummary
                          totals={gstr1Data.b2c_totals}
                          count={gstr1Data.b2c.length}
                          label="B2C Total"
                        />
                      ) : undefined
                    }
                  />
                </TabsContent>

                <TabsContent value="hsn" className="mt-4">
                  <DataTable<HsnRow>
                    id="gstr1.hsn"
                    data={gstr1Data.hsn_summary}
                    columns={HSN_COLUMNS}
                    rowKey={(r, i) => `${r.hsn_code}-${i}`}
                    exportFilename={`gstr1-hsn-${from}-${to}`}
                    defaultSort={{ key: 'taxable_amount', direction: 'desc' }}
                    emptyMessage={t('gst.noHsn')}
                  />
                </TabsContent>
              </Tabs>
            </>
          )}
        </TabsContent>

        {/* ── GSTR-3B ── */}
        <TabsContent value="gstr3b" className="mt-4 space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            {periodControls}
            <Button onClick={fetchGstr3b} disabled={gstr3bLoading}>
              <Search className="mr-2 h-4 w-4" /> {gstr3bLoading ? t('common.loading') : t('gst.generate')}
            </Button>
          </div>

          {gstr3bData && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <p className="text-sm text-muted-foreground">{t('gst.gstinLabel')} <span className="font-mono font-medium">{gstr3bData.gstin || '—'}</span></p>
                <p className="text-sm text-muted-foreground">{t('gst.periodLabel')} <span className="font-medium">{gstr3bData.period}</span></p>
              </div>

              {/* 3.1 Outward Supplies */}
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">{t('gst.outwardSupplies')}</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  <div className="rounded-lg border p-4 space-y-3">
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-xs font-semibold text-muted-foreground uppercase">{t('gst.outwardTaxable')}</p>
                        <p className="text-xs text-muted-foreground mt-0.5">{gstr3bData.section_3_1.a_taxable_outward.description}</p>
                        <p className="text-xs text-muted-foreground">{gstr3bData.section_3_1.a_taxable_outward.invoice_count} {t('gst.invoicesCount')} · {t('gst.taxableValue')} {fmt(gstr3bData.section_3_1.a_taxable_outward.taxable_value)}</p>
                      </div>
                      <p className="text-lg font-bold text-right">{fmt(gstr3bData.section_3_1.a_taxable_outward.total_tax ?? 0)}</p>
                    </div>
                    <div className="grid grid-cols-3 gap-3">
                      <div className="text-center p-2 bg-muted/40 rounded"><p className="text-xs text-muted-foreground">CGST</p><p className="font-semibold">{fmt(gstr3bData.section_3_1.a_taxable_outward.cgst)}</p></div>
                      <div className="text-center p-2 bg-muted/40 rounded"><p className="text-xs text-muted-foreground">SGST</p><p className="font-semibold">{fmt(gstr3bData.section_3_1.a_taxable_outward.sgst)}</p></div>
                      <div className="text-center p-2 bg-muted/40 rounded"><p className="text-xs text-muted-foreground">IGST</p><p className="font-semibold">{fmt(gstr3bData.section_3_1.a_taxable_outward.igst)}</p></div>
                    </div>
                  </div>
                  <div className="rounded-lg border p-3 flex items-center justify-between text-sm">
                    <div>
                      <p className="font-medium text-xs text-muted-foreground uppercase">{t('gst.nonGstOutward')}</p>
                      <p className="text-xs text-muted-foreground">{gstr3bData.section_3_1.e_non_gst.invoice_count} {t('gst.invoicesCount')}</p>
                    </div>
                    <p className="font-semibold">{fmt(gstr3bData.section_3_1.e_non_gst.total_value)}</p>
                  </div>
                </CardContent>
              </Card>

              {/* Section 4 — ITC */}
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">{t('gst.eligibleItc')}</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  <div className="rounded-lg border p-4 space-y-3">
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-xs font-semibold text-muted-foreground uppercase">{t('gst.allOtherItc')}</p>
                        <p className="text-xs text-muted-foreground mt-0.5">{gstr3bData.section_4.a_itc_available.all_other_itc.description}</p>
                        <p className="text-xs text-muted-foreground">{gstr3bData.section_4.a_itc_available.all_other_itc.invoice_count} {t('gst.purchaseInvoicesCount')} · {t('gst.taxable')}: {fmt(gstr3bData.section_4.a_itc_available.all_other_itc.taxable_value)}</p>
                      </div>
                      <p className="text-lg font-bold text-green-700">{fmt(gstr3bData.section_4.a_itc_available.all_other_itc.total_itc)}</p>
                    </div>
                    <div className="grid grid-cols-3 gap-3">
                      <div className="text-center p-2 bg-green-50 rounded"><p className="text-xs text-muted-foreground">CGST</p><p className="font-semibold text-green-700">{fmt(gstr3bData.section_4.a_itc_available.all_other_itc.cgst)}</p></div>
                      <div className="text-center p-2 bg-green-50 rounded"><p className="text-xs text-muted-foreground">SGST</p><p className="font-semibold text-green-700">{fmt(gstr3bData.section_4.a_itc_available.all_other_itc.sgst)}</p></div>
                      <div className="text-center p-2 bg-green-50 rounded"><p className="text-xs text-muted-foreground">IGST</p><p className="font-semibold text-green-700">{fmt(gstr3bData.section_4.a_itc_available.all_other_itc.igst)}</p></div>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Net Tax Payable */}
              <Card className="border-2 border-primary/20">
                <CardHeader className="pb-2"><CardTitle className="text-sm">{t('gst.netTaxPayable')}</CardTitle></CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <TaxCard label={t('gst.cgstPayable')} igst={0} cgst={gstr3bData.net_tax_payable.cgst} sgst={0} total={gstr3bData.net_tax_payable.cgst} />
                    <TaxCard label={t('gst.sgstPayable')} igst={0} cgst={0} sgst={gstr3bData.net_tax_payable.sgst} total={gstr3bData.net_tax_payable.sgst} />
                    <TaxCard label={t('gst.igstPayable')} igst={gstr3bData.net_tax_payable.igst} cgst={0} sgst={0} total={gstr3bData.net_tax_payable.igst} />
                    <div className="rounded-lg border-2 border-primary/30 bg-primary/5 p-4">
                      <p className="text-xs font-medium text-muted-foreground uppercase">{t('gst.totalNetTax')}</p>
                      <p className="text-2xl font-bold text-primary mt-1">{fmt(gstr3bData.net_tax_payable.total)}</p>
                    </div>
                  </div>
                  {gstr3bData.net_tax_payable.total < 0 && (
                    <p className="mt-3 text-sm text-green-700 bg-green-50 rounded px-3 py-2">{t('gst.creditAvailable')}</p>
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
