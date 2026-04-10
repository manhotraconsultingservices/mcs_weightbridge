import { useState } from 'react';
import { Search, Download, FileJson } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import api from '@/services/api';

const fmt = (n: number) => '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => { const d = new Date(); d.setDate(1); return d.toISOString().slice(0, 10); };

function downloadCSV(filename: string, headers: string[], rows: (string | number | null)[][]) {
  const lines = [headers.join(','), ...rows.map(r => r.map(c => `"${c ?? ''}"`).join(','))];
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = filename; a.click();
}

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

function TotalsRow({ totals, label }: { totals: GstTotals; label: string }) {
  return (
    <tr className="bg-muted/30 font-semibold text-sm">
      <td colSpan={2} className="px-3 py-2">{label}</td>
      <td className="px-3 py-2 text-right">{fmt(totals.taxable)}</td>
      <td className="px-3 py-2 text-right">{fmt(totals.cgst)}</td>
      <td className="px-3 py-2 text-right">{fmt(totals.sgst)}</td>
      <td className="px-3 py-2 text-right">{fmt(totals.igst)}</td>
      <td className="px-3 py-2 text-right">{fmt(totals.total)}</td>
    </tr>
  );
}

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

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function GstReportsPage() {
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
        <Label className="text-xs">From</Label>
        <Input type="date" className="w-36" value={from} onChange={e => setFrom(e.target.value)} />
      </div>
      <div className="space-y-1">
        <Label className="text-xs">To</Label>
        <Input type="date" className="w-36" value={to} onChange={e => setTo(e.target.value)} />
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">GST Reports</h1>
        <p className="text-muted-foreground">GSTR-1 summary + JSON export · GSTR-3B monthly return</p>
      </div>

      <Tabs value={mainTab} onValueChange={setMainTab}>
        <TabsList>
          <TabsTrigger value="gstr1">GSTR-1</TabsTrigger>
          <TabsTrigger value="gstr3b">GSTR-3B</TabsTrigger>
        </TabsList>

        {/* ── GSTR-1 ── */}
        <TabsContent value="gstr1" className="mt-4 space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            {periodControls}
            <Button onClick={fetchGstr1} disabled={gstr1Loading}>
              <Search className="mr-2 h-4 w-4" /> {gstr1Loading ? 'Loading…' : 'Generate'}
            </Button>
            <Button variant="outline" onClick={downloadGstr1Json} disabled={jsonDownloading}>
              <FileJson className="mr-2 h-4 w-4" /> {jsonDownloading ? 'Preparing…' : 'JSON Export'}
            </Button>
          </div>

          {gstr1Data && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">B2B Invoices</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{gstr1Data.b2b.length}</p></CardContent></Card>
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">B2C Invoices</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{gstr1Data.b2c.length}</p></CardContent></Card>
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">Total Tax (B2B)</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{fmt(gstr1Data.b2b_totals.cgst + gstr1Data.b2b_totals.sgst + gstr1Data.b2b_totals.igst)}</p></CardContent></Card>
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">Total Tax (B2C)</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{fmt(gstr1Data.b2c_totals.cgst + gstr1Data.b2c_totals.sgst + gstr1Data.b2c_totals.igst)}</p></CardContent></Card>
              </div>

              <Tabs value={gstr1Tab} onValueChange={setGstr1Tab}>
                <TabsList>
                  <TabsTrigger value="b2b">B2B ({gstr1Data.b2b.length})</TabsTrigger>
                  <TabsTrigger value="b2c">B2C ({gstr1Data.b2c.length})</TabsTrigger>
                  <TabsTrigger value="hsn">HSN Summary</TabsTrigger>
                </TabsList>

                <TabsContent value="b2b" className="mt-4">
                  <div className="flex justify-end mb-2">
                    {gstr1Data.b2b.length > 0 && (
                      <Button size="sm" variant="outline" onClick={() => downloadCSV(`gstr1-b2b-${from}-${to}.csv`, ['Invoice No', 'Date', 'Party', 'GSTIN', 'Taxable', 'CGST', 'SGST', 'IGST', 'Total'], gstr1Data.b2b.map(r => [r.invoice_no, r.invoice_date, r.party_name, r.gstin, r.taxable_amount, r.cgst_amount, r.sgst_amount, r.igst_amount, r.grand_total]))}>
                        <Download className="mr-2 h-3.5 w-3.5" /> CSV
                      </Button>
                    )}
                  </div>
                  <Card><CardContent className="p-0">
                    <table className="w-full text-sm">
                      <thead><tr className="border-b bg-muted/50">
                        <th className="px-3 py-2 text-left font-medium text-muted-foreground">Invoice</th>
                        <th className="px-3 py-2 text-left font-medium text-muted-foreground">Party / GSTIN</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">Taxable</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">CGST</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">SGST</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">IGST</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">Total</th>
                      </tr></thead>
                      <tbody>
                        {gstr1Data.b2b.map((r, i) => (
                          <tr key={i} className="border-b hover:bg-muted/20">
                            <td className="px-3 py-2"><p className="font-mono text-xs font-medium">{r.invoice_no}</p><p className="text-xs text-muted-foreground">{r.invoice_date}</p></td>
                            <td className="px-3 py-2"><p className="text-sm">{r.party_name}</p><p className="text-xs text-muted-foreground font-mono">{r.gstin}</p></td>
                            <td className="px-3 py-2 text-right">{fmt(r.taxable_amount)}</td>
                            <td className="px-3 py-2 text-right">{fmt(r.cgst_amount)}</td>
                            <td className="px-3 py-2 text-right">{fmt(r.sgst_amount)}</td>
                            <td className="px-3 py-2 text-right">{fmt(r.igst_amount)}</td>
                            <td className="px-3 py-2 text-right font-semibold">{fmt(r.grand_total)}</td>
                          </tr>
                        ))}
                        {gstr1Data.b2b.length > 0 && <TotalsRow totals={gstr1Data.b2b_totals} label={`Total (${gstr1Data.b2b.length})`} />}
                      </tbody>
                    </table>
                    {gstr1Data.b2b.length === 0 && <div className="py-12 text-center text-muted-foreground text-sm">No B2B invoices in this period.</div>}
                  </CardContent></Card>
                </TabsContent>

                <TabsContent value="b2c" className="mt-4">
                  <div className="flex justify-end mb-2">
                    {gstr1Data.b2c.length > 0 && (
                      <Button size="sm" variant="outline" onClick={() => downloadCSV(`gstr1-b2c-${from}-${to}.csv`, ['Invoice No', 'Date', 'Party', 'Taxable', 'CGST', 'SGST', 'IGST', 'Total'], gstr1Data.b2c.map(r => [r.invoice_no, r.invoice_date, r.party_name, r.taxable_amount, r.cgst_amount, r.sgst_amount, r.igst_amount, r.grand_total]))}>
                        <Download className="mr-2 h-3.5 w-3.5" /> CSV
                      </Button>
                    )}
                  </div>
                  <Card><CardContent className="p-0">
                    <table className="w-full text-sm">
                      <thead><tr className="border-b bg-muted/50">
                        <th className="px-3 py-2 text-left font-medium text-muted-foreground">Invoice</th>
                        <th className="px-3 py-2 text-left font-medium text-muted-foreground">Party</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">Taxable</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">CGST</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">SGST</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">IGST</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">Total</th>
                      </tr></thead>
                      <tbody>
                        {gstr1Data.b2c.map((r, i) => (
                          <tr key={i} className="border-b hover:bg-muted/20">
                            <td className="px-3 py-2"><p className="font-mono text-xs font-medium">{r.invoice_no}</p><p className="text-xs text-muted-foreground">{r.invoice_date}</p></td>
                            <td className="px-3 py-2 text-sm">{r.party_name}</td>
                            <td className="px-3 py-2 text-right">{fmt(r.taxable_amount)}</td>
                            <td className="px-3 py-2 text-right">{fmt(r.cgst_amount)}</td>
                            <td className="px-3 py-2 text-right">{fmt(r.sgst_amount)}</td>
                            <td className="px-3 py-2 text-right">{fmt(r.igst_amount)}</td>
                            <td className="px-3 py-2 text-right font-semibold">{fmt(r.grand_total)}</td>
                          </tr>
                        ))}
                        {gstr1Data.b2c.length > 0 && <TotalsRow totals={gstr1Data.b2c_totals} label={`Total (${gstr1Data.b2c.length})`} />}
                      </tbody>
                    </table>
                    {gstr1Data.b2c.length === 0 && <div className="py-12 text-center text-muted-foreground text-sm">No B2C invoices in this period.</div>}
                  </CardContent></Card>
                </TabsContent>

                <TabsContent value="hsn" className="mt-4">
                  <div className="flex justify-end mb-2">
                    {gstr1Data.hsn_summary.length > 0 && (
                      <Button size="sm" variant="outline" onClick={() => downloadCSV(`gstr1-hsn-${from}-${to}.csv`, ['HSN Code', 'Unit', 'Quantity', 'Taxable', 'CGST', 'SGST', 'IGST'], gstr1Data.hsn_summary.map(r => [r.hsn_code, r.unit, r.quantity, r.taxable_amount, r.cgst_amount, r.sgst_amount, r.igst_amount]))}>
                        <Download className="mr-2 h-3.5 w-3.5" /> CSV
                      </Button>
                    )}
                  </div>
                  <Card><CardContent className="p-0">
                    <table className="w-full text-sm">
                      <thead><tr className="border-b bg-muted/50">
                        <th className="px-3 py-2 text-left font-medium text-muted-foreground">HSN Code</th>
                        <th className="px-3 py-2 text-left font-medium text-muted-foreground">UQC</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">Quantity</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">Taxable</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">CGST</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">SGST</th>
                        <th className="px-3 py-2 text-right font-medium text-muted-foreground">IGST</th>
                      </tr></thead>
                      <tbody>
                        {gstr1Data.hsn_summary.map((r, i) => (
                          <tr key={i} className="border-b hover:bg-muted/20">
                            <td className="px-3 py-2 font-mono font-medium">{r.hsn_code}</td>
                            <td className="px-3 py-2 text-muted-foreground">{r.unit}</td>
                            <td className="px-3 py-2 text-right">{r.quantity.toLocaleString('en-IN', { maximumFractionDigits: 3 })}</td>
                            <td className="px-3 py-2 text-right">{fmt(r.taxable_amount)}</td>
                            <td className="px-3 py-2 text-right">{fmt(r.cgst_amount)}</td>
                            <td className="px-3 py-2 text-right">{fmt(r.sgst_amount)}</td>
                            <td className="px-3 py-2 text-right">{fmt(r.igst_amount)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {gstr1Data.hsn_summary.length === 0 && <div className="py-12 text-center text-muted-foreground text-sm">No HSN data for this period.</div>}
                  </CardContent></Card>
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
              <Search className="mr-2 h-4 w-4" /> {gstr3bLoading ? 'Loading…' : 'Generate'}
            </Button>
          </div>

          {gstr3bData && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <p className="text-sm text-muted-foreground">GSTIN: <span className="font-mono font-medium">{gstr3bData.gstin || '—'}</span></p>
                <p className="text-sm text-muted-foreground">Period: <span className="font-medium">{gstr3bData.period}</span></p>
              </div>

              {/* 3.1 Outward Supplies */}
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">3.1 — Details of Outward Supplies and Inward Supplies Liable to Reverse Charge</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  <div className="rounded-lg border p-4 space-y-3">
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-xs font-semibold text-muted-foreground uppercase">3.1(a) Outward Taxable Supplies</p>
                        <p className="text-xs text-muted-foreground mt-0.5">{gstr3bData.section_3_1.a_taxable_outward.description}</p>
                        <p className="text-xs text-muted-foreground">{gstr3bData.section_3_1.a_taxable_outward.invoice_count} invoices · Taxable value: {fmt(gstr3bData.section_3_1.a_taxable_outward.taxable_value)}</p>
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
                      <p className="font-medium text-xs text-muted-foreground uppercase">3.1(e) Non-GST Outward Supplies</p>
                      <p className="text-xs text-muted-foreground">{gstr3bData.section_3_1.e_non_gst.invoice_count} invoices</p>
                    </div>
                    <p className="font-semibold">{fmt(gstr3bData.section_3_1.e_non_gst.total_value)}</p>
                  </div>
                </CardContent>
              </Card>

              {/* Section 4 — ITC */}
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">4 — Eligible Input Tax Credit (ITC)</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  <div className="rounded-lg border p-4 space-y-3">
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-xs font-semibold text-muted-foreground uppercase">4(A)(5) All Other ITC</p>
                        <p className="text-xs text-muted-foreground mt-0.5">{gstr3bData.section_4.a_itc_available.all_other_itc.description}</p>
                        <p className="text-xs text-muted-foreground">{gstr3bData.section_4.a_itc_available.all_other_itc.invoice_count} purchase invoices · Taxable: {fmt(gstr3bData.section_4.a_itc_available.all_other_itc.taxable_value)}</p>
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
                <CardHeader className="pb-2"><CardTitle className="text-sm">Net Tax Payable (Outward Tax − ITC)</CardTitle></CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <TaxCard label="CGST Payable" igst={0} cgst={gstr3bData.net_tax_payable.cgst} sgst={0} total={gstr3bData.net_tax_payable.cgst} />
                    <TaxCard label="SGST Payable" igst={0} cgst={0} sgst={gstr3bData.net_tax_payable.sgst} total={gstr3bData.net_tax_payable.sgst} />
                    <TaxCard label="IGST Payable" igst={gstr3bData.net_tax_payable.igst} cgst={0} sgst={0} total={gstr3bData.net_tax_payable.igst} />
                    <div className="rounded-lg border-2 border-primary/30 bg-primary/5 p-4">
                      <p className="text-xs font-medium text-muted-foreground uppercase">Total Net Tax</p>
                      <p className="text-2xl font-bold text-primary mt-1">{fmt(gstr3bData.net_tax_payable.total)}</p>
                    </div>
                  </div>
                  {gstr3bData.net_tax_payable.total < 0 && (
                    <p className="mt-3 text-sm text-green-700 bg-green-50 rounded px-3 py-2">ITC exceeds outward tax — credit available for next period.</p>
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
