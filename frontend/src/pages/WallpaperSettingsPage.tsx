import { useEffect, useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Upload, Trash2, ImageIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
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
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Wallpaper</h1>
        <p className="text-sm text-muted-foreground">Set a custom background image for the main content area</p>
      </div>

      {/* Current preview */}
      <div className="rounded-lg border bg-card p-4 space-y-3">
        <p className="text-sm font-medium">Current Wallpaper</p>
        {wallpaperUrl ? (
          <div className="relative">
            <img
              src={wallpaperUrl}
              alt="Current wallpaper"
              className="rounded-md object-cover w-full"
              style={{ maxHeight: 220 }}
            />
            <div className="absolute inset-0 rounded-md bg-background/20" />
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center rounded-md border-2 border-dashed border-muted-foreground/20 bg-muted/30 py-12 gap-2">
            <ImageIcon className="h-10 w-10 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">No wallpaper set</p>
          </div>
        )}
      </div>

      {/* Upload */}
      <div className="rounded-lg border bg-card p-4 space-y-4">
        <p className="text-sm font-medium">Upload New Wallpaper</p>
        <p className="text-xs text-muted-foreground">
          Accepted formats: JPG, PNG, WebP, GIF. Maximum size: 5 MB.<br />
          The image will appear as a background behind page content with a subtle overlay for readability.
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
          >
            <Upload className="h-4 w-4 mr-2" />
            {uploading ? 'Uploading…' : 'Choose Image'}
          </Button>

          {wallpaperUrl && (
            <Button
              variant="outline"
              onClick={handleRemove}
              disabled={removing}
              className="text-destructive hover:text-destructive"
            >
              <Trash2 className="h-4 w-4 mr-2" />
              {removing ? 'Removing…' : 'Remove Wallpaper'}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
