/**
 * PermissionsContext — shared page + tab permission state.
 *
 * Provided by AppLayout in App.tsx (one fetch for the whole session).
 * Consumed by hub pages to filter which tabs are visible for the current role.
 *
 * Tab permission semantics:
 *   - If role_tab_permissions[role][hubPath] is undefined → all tabs shown (no restriction)
 *   - If it is an empty array [] → all tabs shown (empty = unconfigured, safe default)
 *   - If it is ["gate", "tickets"] → only those tab values are shown
 */

import { createContext, useContext } from 'react';
import { HUB_TAB_ROUTES, isPlatformRestricted } from '@/lib/rbac';

// { hubPath → allowed tab values }
export type HubTabMap = Record<string, string[]>;

// { role → HubTabMap }
export type RoleTabPermissions = Record<string, HubTabMap>;

export interface PermissionsContextValue {
  pages: string[];
  roleTabPerms: RoleTabPermissions;
  /**
   * Returns true if the current role is allowed to see the given tab.
   * Returns true when no restriction is configured for the role (the default for
   * admin). A role — including admin — that has configured tabs for a hub sees
   * only those tabs.
   */
  isTabAllowed: (hubPath: string, tabValue: string) => boolean;
}

export const PermissionsContext = createContext<PermissionsContextValue>({
  pages: [],
  roleTabPerms: {},
  isTabAllowed: () => true,
});

export function usePermissions(): PermissionsContextValue {
  return useContext(PermissionsContext);
}

/** Build the context value from data fetched in AppLayout. */
export function buildPermissionsCtx(
  role: string,
  pages: string[],
  roleTabPerms: RoleTabPermissions,
  /** Pages the PLATFORM withheld from this tenant — hides their tabs as well, or a
   *  withheld page would still show a tab that leads nowhere. */
  platformRestrictions?: string[] | null,
): PermissionsContextValue {
  function isTabAllowed(hubPath: string, tabValue: string): boolean {
    const owned = HUB_TAB_ROUTES[hubPath]?.[tabValue] ?? [];
    if (owned.some(rt => isPlatformRestricted(rt, platformRestrictions))) return false;
    // Admin used to short-circuit here, which silently ignored the tab grants an
    // admin had saved for THEMSELVES — a hub tab stayed visible however it was
    // configured. Admin still defaults to everything (no stored config below), but
    // a deliberate restriction now applies to them like any other role.
    const hubPerms = roleTabPerms[role];
    if (!hubPerms) return true;
    const allowed = hubPerms[hubPath];
    if (!allowed || allowed.length === 0) return true;
    return allowed.includes(tabValue);
  }
  return { pages, roleTabPerms, isTabAllowed };
}
