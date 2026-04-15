import { useEffect, useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Upload, Trash2, ImageIcon, Building2, Palette, Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/hooks/useAuth';
import api from '@/services/api';

export default function WallpaperSettingsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [wallpaperUrl, setWallpaperUrl] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);

  // Guard
  useEffect(() => {
    if (user && user.role !== 'admin') navigate('/', { replace: true });
  }, [user, navigate]);

  const fetchInfo = useCallback(async () => {
    try {
      const { data } = await api.get<{ url: string | null }>('/api/v1/app-settings/wallpaper/info');
      setWallpaperUrl(data.url);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => { fetchInfo(); }, [fetchInfo]);

  if (!user || user.role !== 'admin') return null;

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) { toast.error('Please select an image file'); return; }
    if (file.size > 5 * 1024 * 1024) { toast.error('Image must be smaller than 5 MB'); return; }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const { data } = await api.post<{ url: string }>('/api/v1/app-settings/wallpaper', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setWallpaperUrl(data.url);
      window.dispatchEvent(new CustomEvent('appsettings:updated'));
      toast.success('Wallpaper updated');
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to upload wallpaper');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  async function handleRemove() {
    if (!confirm('Remove the current wallpaper?')) return;
    setRemoving(true);
    try {
      await api.delete('/api/v1/app-settings/wallpaper');
      setWallpaperUrl(null);
      window.dispatchEvent(new CustomEvent('appsettings:updated'));
      toast.success('Wallpaper removed');
    } catch {
      toast.error('Failed to remove wallpaper');
    } finally {
      setRemoving(false);
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Palette className="h-6 w-6 text-primary" />
          Branding & Appearance
        </h1>
        <p className="text-sm text-muted-foreground">Customize how your weighbridge software looks</p>
      </div>

      {/* What is this section */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex gap-3 items-start">
            <Info className="h-5 w-5 text-blue-500 shrink-0 mt-0.5" />
            <div className="text-sm text-muted-foreground space-y-1">
              <p><b>Background Wallpaper</b> sets a custom image behind all pages. It adds a professional, branded feel — especially useful when operators or customers can see the screen at the weighbridge counter.</p>
              <p className="text-xs">Tip: Use your company photo, crusher site aerial view, or a branded pattern. The content remains readable with an automatic translucent overlay.</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Company Logo on Invoice */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Building2 className="h-4 w-4" />
            Company Logo (Invoice Header)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-xs text-muted-foreground">
            To set your company logo that appears on invoice PDFs, go to <b>Settings → Company</b> and upload it there.
            The logo will appear in the header of all generated Tax Invoices and Quotation PDFs.
          </p>
          <Button variant="outline" size="sm" onClick={() => navigate('/settings')}>
            Go to Company Settings
          </Button>
        </CardContent>
      </Card>

      {/* Background Wallpaper */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <ImageIcon className="h-4 w-4" />
            Background Wallpaper
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Current preview */}
          {wallpaperUrl ? (
            <div className="relative">
              <img
                src={wallpaperUrl}
                alt="Current wallpaper"
                className="rounded-md object-cover w-full"
                style={{ maxHeight: 220 }}
              />
              <div className="absolute inset-0 rounded-md bg-background/20" />
              <div className="absolute bottom-2 left-2 bg-background/80 rounded px-2 py-1 text-xs text-muted-foreground backdrop-blur">
                Currently active
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center rounded-md border-2 border-dashed border-muted-foreground/20 bg-muted/30 py-10 gap-2">
              <ImageIcon className="h-10 w-10 text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">No wallpaper set — using default background</p>
            </div>
          )}

          <p className="text-xs text-muted-foreground">
            Accepted formats: JPG, PNG, WebP. Maximum size: 5 MB.
          </p>

          <div className="flex gap-3">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              onChange={handleUpload}
              className="hidden"
            />
            <Button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              size="sm"
            >
              <Upload className="h-4 w-4 mr-2" />
              {uploading ? 'Uploading...' : wallpaperUrl ? 'Change Wallpaper' : 'Upload Wallpaper'}
            </Button>

            {wallpaperUrl && (
              <Button
                variant="outline"
                onClick={handleRemove}
                disabled={removing}
                size="sm"
                className="text-destructive hover:text-destructive"
              >
                <Trash2 className="h-4 w-4 mr-2" />
                {removing ? 'Removing...' : 'Remove'}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
