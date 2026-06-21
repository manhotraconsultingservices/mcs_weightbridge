import { useLocation, useNavigate } from 'react-router-dom';
import { LayoutDashboard, Scale, FileText, BarChart2, Menu } from 'lucide-react';

interface Props {
  onOpenSidebar: () => void;
}

const TABS = [
  { label: 'Home',        icon: LayoutDashboard, path: '/' },
  { label: 'Weighbridge', icon: Scale,           path: '/weighbridge' },
  { label: 'Sales',       icon: FileText,        path: '/sales' },
  { label: 'Reports',     icon: BarChart2,       path: '/analytics' },
] as const;

export default function MobileBottomNav({ onOpenSidebar }: Props) {
  const location = useLocation();
  const navigate = useNavigate();

  function isActive(path: string) {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  }

  return (
    <nav
      className="md:hidden fixed bottom-0 left-0 right-0 z-30 flex items-stretch bg-card border-t border-border"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      {TABS.map(({ label, icon: Icon, path }) => (
        <button
          key={path}
          onClick={() => navigate(path)}
          className={`flex-1 flex flex-col items-center justify-center gap-0.5 py-2 text-[10px] font-medium transition-colors ${
            isActive(path)
              ? 'text-primary'
              : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          <Icon className="h-5 w-5" />
          {label}
        </button>
      ))}
      {/* More → opens full sidebar */}
      <button
        onClick={onOpenSidebar}
        className="flex-1 flex flex-col items-center justify-center gap-0.5 py-2 text-[10px] font-medium text-muted-foreground hover:text-foreground transition-colors"
      >
        <Menu className="h-5 w-5" />
        More
      </button>
    </nav>
  );
}
