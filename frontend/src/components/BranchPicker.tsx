import { useEffect, useState } from 'react';
import api from '@/services/api';
import { Building2, ChevronDown } from 'lucide-react';

/**
 * Header branch switcher (Horizon 3 multi-branch). Visible to admins only when
 * at least one branch exists. Selecting a branch stores it in sessionStorage
 * ('active_branch') — api.ts forwards it as X-Branch-Id — and reloads so every
 * branch-scoped list/report re-fetches. "All branches" = consolidated view.
 */
interface Branch { id: string; name: string; code: string; is_active: boolean }

export default function BranchPicker({ role }: { role?: string }) {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [active, setActive] = useState<string>(sessionStorage.getItem('active_branch') || '');
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (role !== 'admin') return;
    api.get<Branch[]>('/api/v1/branches').then(r => setBranches(r.data ?? [])).catch(() => {});
  }, [role]);

  // Only show for admins who actually have branches configured.
  if (role !== 'admin' || branches.length === 0) return null;

  const current = branches.find(b => b.id === active);
  function pick(id: string) {
    if (id) sessionStorage.setItem('active_branch', id);
    else sessionStorage.removeItem('active_branch');
    setActive(id);
    setOpen(false);
    window.location.reload();   // re-fetch everything under the new branch
  }

  return (
    <div className="relative">
      <button onClick={() => setOpen(o => !o)}
        className="inline-flex items-center gap-1.5 rounded-full border bg-white px-3 py-1 text-xs font-medium shadow-sm hover:bg-slate-50">
        <Building2 className="h-3.5 w-3.5 text-emerald-600" />
        {current ? current.name : 'All branches'}
        <ChevronDown className="h-3.5 w-3.5 opacity-60" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 mt-1 z-50 w-52 rounded-lg border bg-white shadow-lg py-1 text-sm">
            <button onClick={() => pick('')} className={`w-full text-left px-3 py-1.5 hover:bg-slate-100 ${!active ? 'font-semibold text-emerald-700' : ''}`}>
              All branches (consolidated)
            </button>
            <div className="border-t my-1" />
            {branches.map(b => (
              <button key={b.id} onClick={() => pick(b.id)}
                className={`w-full text-left px-3 py-1.5 hover:bg-slate-100 ${active === b.id ? 'font-semibold text-emerald-700' : ''}`}>
                {b.name} <span className="text-[10px] text-muted-foreground">· {b.code}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
