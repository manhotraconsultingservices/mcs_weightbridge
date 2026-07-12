import { useNavigate } from 'react-router-dom';
import { ShieldAlert, Home } from 'lucide-react';
import { Button } from '@/components/ui/button';

/** Shown when the current role opens a page it hasn't been granted (route guard). */
export default function NoAccessPage() {
  const nav = useNavigate();
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-amber-100">
        <ShieldAlert className="h-8 w-8 text-amber-600" />
      </div>
      <h1 className="text-xl font-bold text-slate-900">No access to this page</h1>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">
        Your role doesn't have permission to view this page. Ask an administrator to grant
        access under <span className="font-medium">Admin → Role Permissions</span>.
      </p>
      <Button variant="outline" className="mt-5" onClick={() => nav('/', { replace: true })}>
        <Home className="mr-2 h-4 w-4" /> Go to Dashboard
      </Button>
    </div>
  );
}
