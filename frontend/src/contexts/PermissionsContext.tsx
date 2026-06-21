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

// { hubPath → allowed tab values }
export type HubTabMap = Record<string, string[]>;

// { role → HubTabMap }
export type RoleTabPermissions = Record<string, HubTabMap>;

export interface PermissionsContextValue {
  pages: string[];
  roleTabPerms: RoleTabPermissions;
  /**
   * Returns true if the current role is allowed to see the given tab.
   * Always returns true for admin or when no restriction is configured.
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
): PermissionsContextValue {
  function isTabAllowed(hubPath: string, tabValue: string): boolean {
    if (role === 'admin') return true;
    const hubPerms = roleTabPerms[role];
    if (!hubPerms) return true;
    const allowed = hubPerms[hubPath];
    if (!allowed || allowed.length === 0) return true;
    return allowed.includes(tabValue);
  }
  return { pages, roleTabPerms, isTabAllowed };
}
