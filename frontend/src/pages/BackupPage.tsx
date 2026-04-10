import { useState, useEffect, useCallback } from 'react';
import { HardDrive, Plus, Download, Trash2, RotateCcw, Loader2, RefreshCw, AlertTriangle, Cloud, CloudOff, CheckCircle2, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import api from '@/services/api';

interface BackupFile {
  filename: string;
  size_bytes: number;
  size_mb: number;
  created_at: string;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

export default function BackupPage() {
  const [backups, setBackups] = useState<BackupFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createMsg, setCreateMsg] = useState('');

  // Restore dialog
  const [restoreTarget, setRestoreTarget] = useState<BackupFile | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [restoreResult, setRestoreResult] = useState('');

  // Delete dialog
  const [deleteTarget, setDeleteTarget] = useState<BackupFile | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Cloud backup status
  const [cloudStatus, setCloudStatus] = useState<{
    configured: boolean;
    status: string;
    last_backup?: string;
    last_backup_file?: string;
    last_backup_size?: string;
    duration_sec?: number;
    upload_success?: boolean;
    error?: string;
    backup_location?: string;
    next_scheduled?: string;
    client_id?: string;
    local_backup_count?: number;
    message?: string;
  } | null>(null);

  const loadCloudStatus = useCallback(async () => {
    try {
      const { data } = await api.get('/api/v1/backup/cloud-status');
      setCloudStatus(data);
    } catch { setCloudStatus(null); }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<BackupFile[]>('/api/v1/backup/list');
      setBackups(data);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); loadCloudStatus(); }, [load, loadCloudStatus]);

  async function createBackup() {
    setCreating(true); setCreateMsg('');
    try {
      const { data } = await api.post<{ filename: string; size_mb: number; message: string }>('/api/v1/backup/create');
      setCreateMsg(`✓ ${data.message} (${data.size_mb} MB)`);
      load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setCreateMsg(typeof detail === 'string' ? detail : 'Backup failed');
    } finally { setCreating(false); }
  }

  async function downloadBackup(filename: string) {
    try {
      const res = await api.get(`/api/v1/backup/download/${filename}`, { responseType: 'blob' });
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    } catch { /* ignore */ }
  }

  async function restoreBackup() {
    if (!restoreTarget) return;
    setRestoring(true); setRestoreResult('');
    try {
      const { data } = await api.post<{ message: string; warnings: string | null }>(
        `/api/v1/backup/restore/${restoreTarget.filename}`
      );
      setRestoreResult(data.message + (data.warnings ? `\n\nWarnings:\n${data.warnings}` : ''));
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setRestoreResult(typeof detail === 'string' ? `Error: ${detail}` : 'Restore failed');
    } finally { setRestoring(false); }
  }

  async function deleteBackup() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/api/v1/backup/${deleteTarget.filename}`);
      setBackups(b => b.filter(f => f.filename !== deleteTarget.filename));
      setDeleteTarget(null);
    } catch { /* ignore */ }
    finally { setDeleting(false); }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
          <HardDrive className="h-8 w-8 text-primary" /> Backup & Restore
        </h1>
        <p className="text-muted-foreground">Create PostgreSQL database backups and restore from previous snapshots</p>
      </div>

      {/* Cloud Backup Status */}
      {cloudStatus && (
        <Card className={cloudStatus.configured
          ? (cloudStatus.status === 'healthy' ? 'border-green-200 bg-green-50/30' : 'border-red-200 bg-red-50/30')
          : 'border-gray-200'}>
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              {cloudStatus.configured
                ? (cloudStatus.status === 'healthy'
                    ? <Cloud className="h-5 w-5 text-green-600" />
                    : <CloudOff className="h-5 w-5 text-red-600" />)
                : <Cloud className="h-5 w-5 text-muted-foreground" />}
              Cloud Backup (Cloudflare R2)
              {cloudStatus.configured && (
                <Badge className={`ml-2 text-[10px] ${cloudStatus.status === 'healthy' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                  {cloudStatus.status === 'healthy' ? 'Healthy' : 'Error'}
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!cloudStatus.configured ? (
              <p className="text-sm text-muted-foreground">
                Cloud backup not configured. Run <code className="text-xs bg-muted px-1 rounded">Setup-CloudBackup.ps1</code> to enable automated encrypted backups to Cloudflare R2.
              </p>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                  <p className="text-xs text-muted-foreground">Last Backup</p>
                  <p className="font-medium flex items-center gap-1">
                    {cloudStatus.upload_success
                      ? <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
                      : <XCircle className="h-3.5 w-3.5 text-red-600" />}
                    {cloudStatus.last_backup ? formatDate(cloudStatus.last_backup) : 'Never'}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Size</p>
                  <p className="font-medium">{cloudStatus.last_backup_size || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Location</p>
                  <p className="font-mono text-xs">{cloudStatus.backup_location || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Next Scheduled</p>
                  <p className="font-medium">{cloudStatus.next_scheduled ? formatDate(cloudStatus.next_scheduled) : '—'}</p>
                </div>
                {cloudStatus.error && (
                  <div className="col-span-full">
                    <p className="text-xs text-red-600 font-mono bg-red-50 px-2 py-1 rounded">{cloudStatus.error}</p>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Create backup */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Create New Backup</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Runs <code className="text-xs bg-muted px-1 rounded">pg_dump</code> on the current database and saves a timestamped SQL file to the server.
            This may take 10–30 seconds.
          </p>
          <div className="flex items-center gap-3">
            <Button onClick={createBackup} disabled={creating}>
              {creating
                ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Creating backup...</>
                : <><Plus className="mr-2 h-4 w-4" /> Create Backup Now</>
              }
            </Button>
            {createMsg && (
              <span className={`text-sm ${createMsg.startsWith('✓') ? 'text-green-700' : 'text-destructive'}`}>
                {createMsg}
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Backup list */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center justify-between">
            <span>Available Backups ({backups.length})</span>
            <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading && backups.length === 0 ? (
            <div className="py-12 text-center text-sm text-muted-foreground">Loading...</div>
          ) : backups.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
              <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
                <HardDrive className="h-8 w-8 text-muted-foreground/40" />
              </div>
              <h3 className="text-sm font-semibold">No backups yet</h3>
              <p className="mt-1 max-w-xs text-xs text-muted-foreground">
                Click "Create Backup" above to generate your first database backup.
              </p>
            </div>
          ) : (
            <div className="divide-y">
              {backups.map(b => (
                <div key={b.filename} className="flex items-center gap-4 px-4 py-3 hover:bg-muted/30">
                  <HardDrive className="h-5 w-5 text-muted-foreground shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-mono font-medium">{b.filename}</p>
                    <p className="text-xs text-muted-foreground">{formatDate(b.created_at)}</p>
                  </div>
                  <Badge variant="secondary" className="shrink-0">
                    {b.size_mb < 1 ? `${b.size_bytes} B` : `${b.size_mb} MB`}
                  </Badge>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost" size="icon" className="h-8 w-8"
                      title="Download"
                      onClick={() => downloadBackup(b.filename)}
                    >
                      <Download className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost" size="icon" className="h-8 w-8 text-blue-600 hover:text-blue-800"
                      title="Restore from this backup"
                      onClick={() => { setRestoreTarget(b); setRestoreResult(''); }}
                    >
                      <RotateCcw className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      title="Delete backup"
                      onClick={() => setDeleteTarget(b)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Info card */}
      <Card className="border-amber-200 bg-amber-50/50">
        <CardContent className="pt-4">
          <div className="flex gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
            <div className="text-sm text-amber-800 space-y-1">
              <p className="font-medium">Before restoring</p>
              <ul className="list-disc list-inside space-y-0.5 text-amber-700">
                <li>Restore is destructive — it overwrites all current data</li>
                <li>Create a fresh backup before restoring an older one</li>
                <li>All connected users will be logged out after restore</li>
                <li>Requires <code className="text-xs bg-amber-100 px-1 rounded">psql</code> installed on the server</li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Restore Confirm Dialog */}
      <Dialog open={!!restoreTarget} onOpenChange={v => !v && !restoring && setRestoreTarget(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" /> Restore Database?
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              This will replace <strong>all current data</strong> with the backup:
            </p>
            <div className="bg-muted rounded p-2 font-mono text-sm">{restoreTarget?.filename}</div>
            <p className="text-sm text-destructive font-medium">⚠️ This action cannot be undone.</p>
            {restoreResult && (
              <div className={`text-sm rounded p-2 whitespace-pre-wrap ${
                restoreResult.startsWith('Error') ? 'bg-destructive/10 text-destructive' : 'bg-green-100 text-green-800'
              }`}>
                {restoreResult}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRestoreTarget(null)} disabled={restoring}>Cancel</Button>
            <Button variant="destructive" onClick={restoreBackup} disabled={restoring}>
              {restoring ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Restoring...</> : 'Yes, Restore Now'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirm Dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={v => !v && setDeleteTarget(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete Backup?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Permanently delete <strong className="font-mono">{deleteTarget?.filename}</strong>?
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="destructive" onClick={deleteBackup} disabled={deleting}>
              {deleting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
