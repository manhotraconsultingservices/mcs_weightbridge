import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';

export default function LanguageToggle() {
  const { i18n } = useTranslation();
  const isHindi = i18n.language === 'hi';

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => i18n.changeLanguage(isHindi ? 'en' : 'hi')}
      className="h-7 px-2 text-xs font-medium text-muted-foreground hover:text-foreground border border-border/50 hover:border-border"
      title={isHindi ? 'Switch to English' : 'हिंदी में बदलें'}
    >
      {isHindi ? 'EN' : 'हिं'}
    </Button>
  );
}
