/**
 * Reports hub — a grouped left sub-nav (sub-categories) + the selected report on
 * the right. Replaces the old 14-tab horizontal strip: each report is a command
 * in the left list, organised into sub-categories. `?tab=` keeps deep-links
 * working (e.g. the Day Book sidebar item → /reports?tab=eod). Mobile gets a
 * single grouped dropdown.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { CreditCard, BookOpen, FileBarChart, BarChart3, ShieldCheck, Shield, XCircle, PieChart, TrendingUp, ShieldAlert, DoorOpen, Ticket, Wallet, HandCoins } from 'lucide-react';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import PaymentsPage from './PaymentsPage';
import LedgerPage from './LedgerPage';
import GstReportsPage from './GstReportsPage';
import ReportsPage from './ReportsPage';
import CompliancePage from './CompliancePage';
import AuditPage from './AuditPage';
import WriteOffsReportPage from './WriteOffsReportPage';
import GstSplitReportPage from './GstSplitReportPage';
import Gstr2bReconcilePage from './Gstr2bReconcilePage';
import SalesStatusReportPage from './SalesStatusReportPage';
import AnomalyReportPage from './AnomalyReportPage';
import GatePassRegisterPage from './GatePassRegisterPage';
import TokenRegisterPage from './TokenRegisterPage';
import EodSummaryReportPage from './EodSummaryReportPage';
import OperatorCashEodPage from './OperatorCashEodPage';

type Tab = 'payments' | 'eod' | 'operator-cash' | 'statement' | 'gst' | 'gstr2b' | 'gst-split' | 'sales-status' | 'reports' | 'write-offs' | 'compliance' | 'activity' | 'anomaly' | 'gate-passes' | 'token-register';

export default function ReportsHubPage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const loc = useLocation();
  // Default to "reports" (P&L) so the /reports URL behaves like before.
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'reports';
  const [tab, setTab] = useState<Tab>(initial);

  // User picks a report → update state + URL.
  const selectTab = (v: Tab) => {
    setTab(v);
    const params = new URLSearchParams(loc.search);
    params.set('tab', v);
    nav({ search: params.toString() }, { replace: true });
  };

  // Deep-link / sidebar nav (e.g. /reports?tab=eod) → sync URL into state.
  useEffect(() => {
    const urlTab = new URLSearchParams(loc.search).get('tab') as Tab | null;
    if (urlTab && urlTab !== tab) setTab(urlTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loc.search]);

  const META: Record<Tab, { label: string; icon: React.ElementType }> = {
    payments: { label: t('payment.title'), icon: CreditCard },
    eod: { label: 'Day Book (EOD)', icon: Wallet },
    'operator-cash': { label: 'Operator Cash (EOD)', icon: HandCoins },
    statement: { label: t('reports.accountStatement'), icon: BookOpen },
    gst: { label: t('reports.gstReturns'), icon: FileBarChart },
    gstr2b: { label: t('reports.gstr2b'), icon: FileBarChart },
    'gst-split': { label: t('reports.gstVsCash'), icon: PieChart },
    'sales-status': { label: t('reports.salesByStatus'), icon: TrendingUp },
    reports: { label: t('reports.plSales'), icon: BarChart3 },
    'write-offs': { label: t('reports.writeoffs'), icon: XCircle },
    compliance: { label: t('reports.documents'), icon: ShieldCheck },
    activity: { label: t('reports.activityLog'), icon: Shield },
    anomaly: { label: t('reports.anomaly'), icon: ShieldAlert },
    'gate-passes': { label: t('hubs.reports.gatePassRegister'), icon: DoorOpen },
    'token-register': { label: t('hubs.reports.tokenRegister'), icon: Ticket },
  };

  // Sub-categories — the grouped left nav.
  const GROUPS: { label: string; items: Tab[] }[] = [
    { label: 'Daily & Operations', items: ['eod', 'operator-cash', 'gate-passes', 'token-register'] },
    { label: 'Sales & GST',        items: ['gst', 'gstr2b', 'gst-split', 'sales-status'] },
    { label: 'Financials',         items: ['reports', 'statement', 'payments', 'write-offs'] },
    { label: 'Compliance & Audit', items: ['compliance', 'activity', 'anomaly'] },
  ];

  // Mobile: one flat dropdown, ordered + prefixed by sub-category.
  const mobileOptions = GROUPS.flatMap(g =>
    g.items.map(v => ({ value: v, label: `${g.label} · ${META[v].label}` })));

  function renderReport(x: Tab) {
    switch (x) {
      case 'payments': return <PaymentsPage />;
      case 'eod': return <EodSummaryReportPage />;
      case 'operator-cash': return <OperatorCashEodPage />;
      case 'statement': return <LedgerPage />;
      case 'gst': return <GstReportsPage />;
      case 'gstr2b': return <Gstr2bReconcilePage />;
      case 'gst-split': return <GstSplitReportPage />;
      case 'sales-status': return <SalesStatusReportPage />;
      case 'reports': return <ReportsPage />;
      case 'write-offs': return <WriteOffsReportPage />;
      case 'compliance': return <CompliancePage />;
      case 'activity': return <AuditPage />;
      case 'anomaly': return <AnomalyReportPage />;
      case 'gate-passes': return <GatePassRegisterPage />;
      case 'token-register': return <TokenRegisterPage />;
      default: return null;
    }
  }

  const active = META[tab];

  return (
    <div className="space-y-3">
      {/* Mobile: grouped dropdown */}
      <div className="md:hidden">
        <MobileTabSelect value={tab} onValueChange={(v) => selectTab(v as Tab)} options={mobileOptions} />
      </div>

      <div className="md:flex md:gap-5">
        {/* Desktop left sub-nav — sub-categories with report commands */}
        <aside className="hidden md:block w-56 shrink-0">
          <nav className="sticky top-2 space-y-4">
            {GROUPS.map(g => (
              <div key={g.label}>
                <p className="px-2 mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{g.label}</p>
                <ul className="space-y-0.5">
                  {g.items.map(v => {
                    const Icon = META[v].icon;
                    const isActive = tab === v;
                    return (
                      <li key={v}>
                        <button
                          onClick={() => selectTab(v)}
                          className={`w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-left transition-colors ${isActive ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'}`}
                        >
                          <Icon className="h-4 w-4 shrink-0" />
                          <span className="truncate">{META[v].label}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>
        </aside>

        {/* Selected report */}
        <div className="flex-1 min-w-0">
          <div className="mb-3 flex items-center gap-2 md:hidden">
            {active && <active.icon className="h-4 w-4 text-muted-foreground" />}
            <h2 className="text-base font-semibold">{active?.label}</h2>
          </div>
          {renderReport(tab)}
        </div>
      </div>
    </div>
  );
}
