import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import en from './locales/en.json';
import hi from './locales/hi.json';

// ── Industry terminology overlays ────────────────────────────────────────────
// Per-vertical label bundles that override a small subset of base keys
// (e.g. maize: Customer→Buyer, Supplier→Farmer, Token→Weighment). Only the
// keys present in the overlay change; everything else falls through to base.
import maizeEn from './locales/industry/maize.en.json';
import maizeHi from './locales/industry/maize.hi.json';

const INDUSTRY_OVERLAYS: Record<string, { en: object; hi: object }> = {
  maize_trader: { en: maizeEn, hi: maizeHi },
};

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      hi: { translation: hi },
    },
    fallbackLng: 'en',
    detection: {
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: 'weighbridge_lang',
      caches: ['localStorage'],
    },
    interpolation: {
      escapeValue: false,
    },
  });

/**
 * Apply (or clear) an industry's terminology overlay. Resets to the base
 * bundles first so switching industries in the same tab can't leak labels,
 * then deep-merges the overlay (overwriting only the keys it defines).
 */
export function applyIndustryTerminology(industry?: string | null) {
  i18n.addResourceBundle('en', 'translation', en, true, true);
  i18n.addResourceBundle('hi', 'translation', hi, true, true);
  const ov = industry ? INDUSTRY_OVERLAYS[industry] : undefined;
  if (ov) {
    i18n.addResourceBundle('en', 'translation', ov.en, true, true);
    i18n.addResourceBundle('hi', 'translation', ov.hi, true, true);
  }
}

// Bootstrap: on a reload while logged in, re-apply the stored tenant's overlay.
try {
  const ind = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('tenant_industry') : null;
  if (ind) applyIndustryTerminology(ind);
} catch { /* sessionStorage unavailable — ignore */ }

export default i18n;
