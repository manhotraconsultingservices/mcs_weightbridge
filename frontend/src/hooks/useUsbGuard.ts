import { useState, useEffect, useCallback, useRef } from 'react';
import { toast } from 'sonner';
import api from '@/services/api';

interface UsbStatus {
  authorized: boolean;
  method: 'usb' | 'usb_legacy' | 'client_usb' | 'recovery' | null;
  expires_at: string | null;
}

// File System Access API types (Chrome/Edge 86+)
interface FileSystemFileHandle {
  getFile(): Promise<File>;
  name: string;
}
interface FileSystemDirectoryHandle {
  getFileHandle(name: string, options?: { create?: boolean }): Promise<FileSystemFileHandle & { createWritable(): Promise<FileSystemWritableFileStream> }>;
}
interface FileSystemWritableFileStream {
  write(data: ArrayBuffer | Blob): Promise<void>;
  close(): Promise<void>;
}
interface ShowOpenFilePickerOptions {
  multiple?: boolean;
  excludeAcceptAllOption?: boolean;
  types?: Array<{ description?: string; accept: Record<string, string[]> }>;
}
declare global {
  interface Window {
    showOpenFilePicker?: (opts?: ShowOpenFilePickerOptions) => Promise<FileSystemFileHandle[]>;
    showDirectoryPicker?: (opts?: { mode?: string; startIn?: string }) => Promise<FileSystemDirectoryHandle>;
  }
}

export function useUsbGuard() {
  const [status, setStatus] = useState<UsbStatus>({ authorized: false, method: null, expires_at: null });
  const [loading, setLoading] = useState(true);

  // Persistent file handle — kept in ref so re-reads don't cause renders
  const fileHandleRef = useRef<FileSystemFileHandle | null>(null);
  // Original key content stored to detect USB-swap attacks
  const keyContentRef = useRef<string | null>(null);
  // Directory handle on USB drive for auto-backups
  const dirHandleRef  = useRef<FileSystemDirectoryHandle | null>(null);
  // Backup interval ref
  const backupIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /**
   * Revoke the current user's client USB session (DB) and clear local state.
   * Called automatically when pendrive is removed, or manually via "Lock" button.
   */
  const revokeSession = useCallback(async () => {
    fileHandleRef.current = null;
    keyContentRef.current = null;
    dirHandleRef.current = null;
    if (backupIntervalRef.current) {
      clearInterval(backupIntervalRef.current);
      backupIntervalRef.current = null;
    }
    try { await api.post('/api/v1/usb-guard/revoke-session', {}); } catch { /* best-effort */ }
    setStatus({ authorized: false, method: null, expires_at: null });
  }, []);

  /**
   * Write one supplement backup blob to the USB directory.
   */
  const writeBackup = useCallback(async () => {
    if (!dirHandleRef.current) return;
    try {
      const { data } = await api.get<Blob>('/api/v1/private-invoices/export-encrypted', { responseType: 'blob' });
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const filename = `supplement_backup_${ts}.enc`;
      const fh = await dirHandleRef.current.getFileHandle(filename, { create: true });
      const writable = await fh.createWritable();
      await writable.write(data as unknown as ArrayBuffer);
      await writable.close();
      toast.info(`Supplement backup saved to USB: ${filename}`);
    } catch (err) {
      console.warn('Supplement USB auto-backup failed:', err);
    }
  }, []);

  /**
   * Start hourly backup timer (called after successful auth with directory).
   */
  const startBackupTimer = useCallback(() => {
    if (backupIntervalRef.current) clearInterval(backupIntervalRef.current);
    backupIntervalRef.current = setInterval(writeBackup, 60 * 60 * 1000); // 1 hour
  }, [writeBackup]);

  /**
   * Poll USB status every 10 s.
   * If authenticated via client USB, ALSO try to re-read the actual key file
   * from the USB drive. If the drive has been removed, `handle.getFile()` throws
   * and we immediately revoke access — no waiting for the DB session to expire.
   */
  const refresh = useCallback(async () => {
    try {
      // ── Live pendrive check ───────────────────────────────────────────────
      if (fileHandleRef.current) {
        try {
          const file    = await fileHandleRef.current.getFile();
          const content = (await file.text()).trim();
          // Content mismatch → USB was swapped (security)
          if (keyContentRef.current && content !== keyContentRef.current) {
            await revokeSession();
            return;
          }
        } catch {
          // getFile() threw → drive is no longer accessible → revoke immediately
          await revokeSession();
          return;
        }
      }

      const { data } = await api.get<UsbStatus>('/api/v1/usb-guard/status');
      setStatus(data);

      // If session expired / server USB removed → clear file handle too
      if (!data.authorized && fileHandleRef.current) {
        fileHandleRef.current = null;
        keyContentRef.current = null;
        dirHandleRef.current = null;
        if (backupIntervalRef.current) {
          clearInterval(backupIntervalRef.current);
          backupIntervalRef.current = null;
        }
      }
    } catch {
      setStatus({ authorized: false, method: null, expires_at: null });
    } finally {
      setLoading(false);
    }
  }, [revokeSession]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10_000);   // poll every 10 s
    return () => {
      clearInterval(id);
      if (backupIntervalRef.current) clearInterval(backupIntervalRef.current);
    };
  }, [refresh]);

  /**
   * HMAC challenge-response authentication using a FileSystemFileHandle.
   * After success, optionally prompts for a USB directory for auto-backups.
   *
   * Key file on USB: "<uuid>:<hmac_secret_hex>"
   *   uuid            — identifies the key in the database
   *   hmac_secret_hex — 256-bit secret; NEVER transmitted to server
   */
  const clientAuth = useCallback(async (fileHandle: FileSystemFileHandle): Promise<void> => {
    // Read file content right now (USB must be physically present)
    const file        = await fileHandle.getFile();
    const fileContent = (await file.text()).trim();

    const colonIdx = fileContent.indexOf(':');
    if (colonIdx === -1) {
      throw new Error(
        'Old key format — not supported.\n' +
        'Re-generate the key using setup_usb_key.py on the server.'
      );
    }
    const key_uuid       = fileContent.substring(0, colonIdx).trim();
    const hmac_secret_hex = fileContent.substring(colonIdx + 1).trim();
    if (!key_uuid || hmac_secret_hex.length !== 64) {
      throw new Error('Invalid key file. Expected <uuid>:<64-hex-secret>.');
    }

    // Step 1: Get challenge nonce
    const { data: challenge } = await api.get<{ nonce: string; user_id: string }>('/api/v1/usb-guard/challenge');
    const { nonce, user_id } = challenge;

    // Step 2: Compute HMAC-SHA256 in browser — secret never leaves the tab
    const secretBytes  = hexToBytes(hmac_secret_hex);
    const messageBytes = new TextEncoder().encode(`${nonce}:${user_id}`);
    const cryptoKey    = await crypto.subtle.importKey(
      'raw', secretBytes.buffer as ArrayBuffer, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
    );
    const sigBuffer = await crypto.subtle.sign('HMAC', cryptoKey, messageBytes.buffer as ArrayBuffer);
    const signature = bytesToHex(new Uint8Array(sigBuffer));

    // Step 3: Send {key_uuid, nonce, signature} — NOT the secret
    await api.post('/api/v1/usb-guard/client-auth', { key_uuid, nonce, signature });

    // Store handle for live re-verification on every poll
    fileHandleRef.current = fileHandle;
    keyContentRef.current = fileContent;

    await refresh();

    // Step 4: Optionally request a directory on the USB drive for auto-backups
    if (typeof window.showDirectoryPicker === 'function') {
      try {
        const dirHandle = await window.showDirectoryPicker({ mode: 'readwrite', startIn: 'downloads' });
        if (dirHandle) {
          dirHandleRef.current = dirHandle;
          startBackupTimer();
          // Immediately write a backup
          await writeBackup();
          toast.success('USB auto-backup directory selected. Backups will run hourly.');
        }
      } catch {
        // User cancelled directory picker — backups disabled, that's OK
        toast.info('No backup directory selected. Auto-backup skipped.');
      }
    }
  }, [refresh, startBackupTimer, writeBackup]);

  /** Manually trigger a supplement backup to USB now. */
  const backupNow = useCallback(async () => {
    if (!dirHandleRef.current) {
      toast.error('No USB backup directory selected. Authenticate with USB first.');
      return;
    }
    await writeBackup();
  }, [writeBackup]);

  return { ...status, loading, refresh, clientAuth, revokeSession, backupNow, hasBackupDir: !!dirHandleRef.current };
}


// ─── Crypto helpers ───────────────────────────────────────────────────────────

function hexToBytes(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2)
    bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  return bytes;
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
}
