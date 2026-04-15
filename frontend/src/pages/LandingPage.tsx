import { useNavigate } from 'react-router-dom';
import {
  Scale, Zap, Camera, BarChart3, FileText, Shield, MessageCircle, Phone, Mail,
  CheckCircle2, ArrowRight, ChevronDown, ChevronUp, IndianRupee, Clock,
  Users, Monitor, RefreshCw, Star, MapPin,
  Timer, Receipt, AlertTriangle
} from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';

/* ------------------------------------------------------------------ */
/*  Data                                                               */
/* ------------------------------------------------------------------ */

const PAIN_POINTS = [
  { icon: Scale, text: 'Manual weight entry errors costing you lakhs every year' },
  { icon: Clock, text: 'Hours wasted on Tally data entry after every truck' },
  { icon: FileText, text: 'GST filing headaches and last-minute scrambles every month' },
  { icon: Camera, text: 'No photo proof — leading to disputes with transporters' },
  { icon: IndianRupee, text: 'Delayed invoicing means delayed payments and cash flow gaps' },
  { icon: Users, text: 'No visibility into daily operations when you are away from the site' },
];

const FEATURES = [
  {
    icon: Scale,
    title: 'Two-Stage Weighment',
    description: 'Live weight scale integration with stability detection. Gross and tare weight captured automatically — zero manual entry errors.',
  },
  {
    icon: FileText,
    title: 'Auto GST Invoicing',
    description: 'Invoice auto-generated on weighment completion. CGST/SGST/IGST auto-calculated. B2B and B2C support with eInvoice IRN.',
  },
  {
    icon: Camera,
    title: 'Camera Proof at Weighbridge',
    description: 'Auto-captures front and top camera snapshots at both weighments. Timestamped photo proof eliminates disputes.',
  },
  {
    icon: RefreshCw,
    title: 'One-Click Tally Sync',
    description: 'Push invoices, parties, and orders directly to Tally Prime. No more manual voucher entry. Bulk sync supported.',
  },
  {
    icon: BarChart3,
    title: 'GSTR-1 & GSTR-3B Ready',
    description: 'Generate GSTR-1 (B2B + B2C + HSN) and GSTR-3B reports instantly. Download in GSTN portal JSON format.',
  },
  {
    icon: MessageCircle,
    title: 'Instant Alerts & Reports',
    description: 'Telegram and WhatsApp notifications for every weighment, invoice, and payment. Daily summary reports to your phone.',
  },
  {
    icon: Shield,
    title: 'Bank-Grade Security',
    description: 'AES-256 encryption, hardware-locked licensing, brute-force protection, daily encrypted cloud backups, and USB-secured private billing.',
  },
  {
    icon: Monitor,
    title: 'Multi-Site Management',
    description: 'Manage multiple crusher sites from one dashboard. Each site gets its own database, users, and settings. Cloud SaaS ready.',
  },
];

const HOW_IT_WORKS = [
  {
    step: 1,
    title: 'Vehicle Arrives',
    description: 'Create token, select party and product. Camera auto-captures. First weight recorded from live scale.',
  },
  {
    step: 2,
    title: 'Weighment Complete',
    description: 'Second weight recorded. Net weight calculated. GST invoice auto-generated with correct rates and taxes.',
  },
  {
    step: 3,
    title: 'Synced & Filed',
    description: 'Invoice pushed to Tally. GSTR reports ready for filing. Payment tracked. Alerts sent to your phone.',
  },
];

const RESULTS = [
  {
    icon: Timer,
    metric: '2 Hours/Day',
    label: 'Saved on Tally Entry',
    description: 'Auto-sync eliminates manual voucher creation. What took hours now takes one click.',
  },
  {
    icon: IndianRupee,
    metric: '100%',
    label: 'Accurate Invoicing',
    description: 'Auto-calculated GST, eInvoice IRN, and gap-free numbering. No more manual errors or missed entries.',
  },
  {
    icon: Receipt,
    metric: '3 Days to 3 Min',
    label: 'GST Filing Time',
    description: 'GSTR-1 JSON download and GSTR-3B report generated instantly. Upload directly to GSTN portal.',
  },
  {
    icon: AlertTriangle,
    metric: 'Zero',
    label: 'Transporter Disputes',
    description: 'Timestamped camera proof at both weighments. Every truck photographed, every load documented.',
  },
];

const STATS = [
  { value: '50+', label: 'Installations' },
  { value: 'Pan India', label: 'J&K, Punjab, UP, UK & more' },
  { value: '10L+', label: 'Invoices Processed' },
  { value: '99.9%', label: 'Uptime' },
];

const FAQS = [
  {
    q: 'Does it work with my existing weighbridge?',
    a: 'Yes. WeighBridge Setu connects to any electronic weighbridge via serial port (RS-232). We support all major Indian weighbridge brands including Essae, Avery, and CAS.',
  },
  {
    q: 'Do I need internet for it to work?',
    a: 'The core system works fully offline on your local network. Internet is needed only for cloud backup, Telegram alerts, eInvoice IRN generation, and remote access via Cloudflare tunnel.',
  },
  {
    q: 'Can I use it on multiple computers?',
    a: 'Absolutely. The server runs on one machine and any computer, tablet, or phone on your local network can access it via browser. No software installation needed on client machines.',
  },
  {
    q: 'Does it support Tally Prime?',
    a: 'Yes. One-click sync pushes sales invoices, purchase invoices, party masters, sales orders, and purchase orders directly to Tally Prime. Bulk sync is also supported.',
  },
  {
    q: 'What about GST eInvoice (IRN)?',
    a: 'Built-in NIC eInvoice integration. IRN is auto-generated when you finalize a B2B invoice. QR code and IRN number printed on the invoice PDF. Cancel IRN within 24 hours if needed.',
  },
  {
    q: 'How is my data secured?',
    a: 'AES-256 encryption for sensitive data, hardware-locked licensing, login brute-force protection, daily encrypted cloud backups to Cloudflare R2, and USB-secured private billing for non-GST transactions.',
  },
  {
    q: 'What is the pricing?',
    a: 'We offer flexible plans based on your site requirements. Contact us on WhatsApp or call for a custom quote. Installation, training, and Tally setup are included.',
  },
];

/* ------------------------------------------------------------------ */
/*  Components                                                         */
/* ------------------------------------------------------------------ */

function FAQItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-border last:border-0">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between py-4 text-left hover:text-primary transition-colors"
      >
        <span className="font-medium text-sm pr-4">{q}</span>
        {open ? <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />}
      </button>
      {open && <p className="pb-4 text-sm text-muted-foreground leading-relaxed">{a}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Page                                                          */
/* ------------------------------------------------------------------ */

export default function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* ── Sticky Nav ────────────────────────────────────── */}
      <nav className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Scale className="h-5 w-5" />
            </div>
            <div>
              <span className="font-bold text-lg leading-none">WeighBridge Setu</span>
              <span className="block text-[10px] text-muted-foreground leading-none mt-0.5">by Manhotra Consulting</span>
            </div>
          </div>
          <div className="hidden md:flex items-center gap-6 text-sm text-muted-foreground">
            <a href="#why-switch" className="hover:text-foreground transition-colors">Why Switch</a>
            <a href="#features" className="hover:text-foreground transition-colors">Features</a>
            <a href="#how-it-works" className="hover:text-foreground transition-colors">How It Works</a>
            <a href="#results" className="hover:text-foreground transition-colors">Results</a>
            <a href="#faq" className="hover:text-foreground transition-colors">FAQ</a>
            <a href="#contact" className="hover:text-foreground transition-colors">Contact</a>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => navigate('/login')}>
              Sign In
            </Button>
            <a
              href="https://wa.me/917011189371?text=Hi%2C%20I%27m%20interested%20in%20WeighBridge%20Setu%20demo"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button size="sm" className="gap-1.5">
                <MessageCircle className="h-3.5 w-3.5" />
                Book Demo
              </Button>
            </a>
          </div>
        </div>
      </nav>

      {/* ── Hero ──────────────────────────────────────────── */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-primary/5 via-background to-primary/3" />
        <div className="relative mx-auto max-w-6xl px-4 sm:px-6 py-20 sm:py-28 lg:py-36">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-xs font-medium text-primary mb-6">
              <Zap className="h-3 w-3" />
              Trusted by 50+ stone crushers across India
            </div>
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight leading-[1.1]">
              Automate Your Weighbridge.{' '}
              <span className="text-primary">Get Paid Faster.</span>
            </h1>
            <p className="mt-6 text-lg sm:text-xl text-muted-foreground max-w-2xl leading-relaxed">
              GST-compliant weighbridge + invoicing software built for Indian stone crushers and mining operations.
              Two-stage weighment, auto-invoicing, Tally sync, camera proof, and GSTR filing — all in one system.
            </p>
            <div className="mt-8 flex flex-col sm:flex-row items-start gap-3">
              <a
                href="https://wa.me/917011189371?text=Hi%2C%20I%27m%20interested%20in%20a%20free%20demo%20of%20WeighBridge%20Setu"
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button size="lg" className="gap-2 text-base px-8">
                  <MessageCircle className="h-4 w-4" />
                  Book Free Demo
                </Button>
              </a>
              <a href="tel:+917011189371">
                <Button variant="outline" size="lg" className="gap-2 text-base px-8">
                  <Phone className="h-4 w-4" />
                  Call: +91 70111 89371
                </Button>
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* ── Stats Strip ───────────────────────────────────── */}
      <section className="border-y border-border bg-muted/30">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-8">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
            {STATS.map((s) => (
              <div key={s.label} className="text-center">
                <div className="text-3xl sm:text-4xl font-bold text-primary">{s.value}</div>
                <div className="mt-1 text-sm text-muted-foreground">{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Why Switch ────────────────────────────────────── */}
      <section id="why-switch" className="mx-auto max-w-6xl px-4 sm:px-6 py-16 sm:py-24">
        <div className="text-center mb-12">
          <h2 className="text-3xl sm:text-4xl font-bold">Why Crusher Owners Are Switching</h2>
          <p className="mt-3 text-muted-foreground max-w-xl mx-auto">
            If any of these sound familiar, you are losing money every single day.
          </p>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {PAIN_POINTS.map(({ icon: Icon, text }) => (
            <div key={text} className="flex items-start gap-3 rounded-lg border border-destructive/20 bg-destructive/5 p-4">
              <Icon className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
              <span className="text-sm">{text}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ── Features ──────────────────────────────────────── */}
      <section id="features" className="bg-muted/30 border-y border-border">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 sm:py-24">
          <div className="text-center mb-12">
            <h2 className="text-3xl sm:text-4xl font-bold">Everything You Need. Nothing You Don't.</h2>
            <p className="mt-3 text-muted-foreground max-w-xl mx-auto">
              Built by people who understand the stone crusher business — not a generic ERP with bolted-on weighbridge features.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {FEATURES.map(({ icon: Icon, title, description }) => (
              <div key={title} className="rounded-xl border border-border bg-background p-6 hover:shadow-md transition-shadow">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary mb-4">
                  <Icon className="h-5 w-5" />
                </div>
                <h3 className="font-semibold mb-2">{title}</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">{description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How It Works ──────────────────────────────────── */}
      <section id="how-it-works" className="mx-auto max-w-6xl px-4 sm:px-6 py-16 sm:py-24">
        <div className="text-center mb-12">
          <h2 className="text-3xl sm:text-4xl font-bold">Simple as 1-2-3</h2>
          <p className="mt-3 text-muted-foreground">From truck arrival to Tally entry — fully automated.</p>
        </div>
        <div className="grid md:grid-cols-3 gap-8">
          {HOW_IT_WORKS.map(({ step, title, description }) => (
            <div key={step} className="relative text-center">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-primary text-primary-foreground text-xl font-bold mb-4">
                {step}
              </div>
              <h3 className="font-semibold text-lg mb-2">{title}</h3>
              <p className="text-sm text-muted-foreground leading-relaxed">{description}</p>
              {step < 3 && (
                <ArrowRight className="hidden md:block absolute top-7 -right-4 h-5 w-5 text-muted-foreground/40" />
              )}
            </div>
          ))}
        </div>
      </section>

      {/* ── Results ───────────────────────────────────────── */}
      <section id="results" className="bg-muted/30 border-y border-border">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 sm:py-24">
          <div className="text-center mb-12">
            <h2 className="text-3xl sm:text-4xl font-bold">Real Results from Real Crushers</h2>
            <p className="mt-3 text-muted-foreground max-w-xl mx-auto">
              Here is what our customers achieved within the first month of switching.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {RESULTS.map(({ icon: Icon, metric, label, description }) => (
              <div key={label} className="rounded-xl border border-border bg-background p-6 text-center">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-green-100 text-green-700 mb-4">
                  <Icon className="h-6 w-6" />
                </div>
                <div className="text-2xl sm:text-3xl font-bold text-primary mb-1">{metric}</div>
                <div className="font-semibold text-sm mb-2">{label}</div>
                <p className="text-xs text-muted-foreground leading-relaxed">{description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Social Proof / Testimonials ───────────────────── */}
      <section className="mx-auto max-w-6xl px-4 sm:px-6 py-16 sm:py-24">
        <div className="text-center mb-12">
          <h2 className="text-3xl sm:text-4xl font-bold">Trusted by Crusher Owners Across India</h2>
        </div>
        <div className="grid md:grid-cols-3 gap-6">
          {[
            {
              quote: 'We used to spend 2 hours daily on Tally entries. Now it is one click. Saved us a full-time data entry person.',
              name: 'Rajesh P.',
              role: 'Owner, Stone Crusher',
              location: 'Maharashtra',
            },
            {
              quote: 'Camera proof at weighbridge ended all disputes with transporters. The software paid for itself in the first month.',
              name: 'Amit S.',
              role: 'Manager, Mining Operations',
              location: 'Rajasthan',
            },
            {
              quote: 'GST filing used to take 3 days. Now I download GSTR-1 JSON and upload directly. No CA dependency for monthly filing.',
              name: 'Vikram K.',
              role: 'Owner, Aggregate Supplier',
              location: 'Madhya Pradesh',
            },
          ].map((t) => (
            <div key={t.name} className="rounded-xl border border-border bg-background p-6">
              <div className="flex gap-0.5 mb-3">
                {[1, 2, 3, 4, 5].map((s) => (
                  <Star key={s} className="h-4 w-4 fill-amber-400 text-amber-400" />
                ))}
              </div>
              <p className="text-sm leading-relaxed mb-4 italic text-muted-foreground">"{t.quote}"</p>
              <div>
                <p className="font-semibold text-sm">{t.name}</p>
                <p className="text-xs text-muted-foreground">{t.role}</p>
                <p className="text-xs text-muted-foreground flex items-center gap-1 mt-0.5">
                  <MapPin className="h-3 w-3" /> {t.location}
                </p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── What's Included (Pricing) ─────────────────────── */}
      <section id="pricing" className="bg-muted/30 border-y border-border">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 sm:py-24">
          <div className="text-center mb-12">
            <h2 className="text-3xl sm:text-4xl font-bold">What's Included</h2>
            <p className="mt-3 text-muted-foreground">No hidden costs. Everything you need to get started.</p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 max-w-3xl mx-auto">
            {[
              'Full software installation & setup',
              'Tally Prime integration configuration',
              'Camera setup & configuration',
              'Weight scale integration',
              'Staff training (on-site or remote)',
              'Dedicated WhatsApp support',
              'Daily cloud backup (encrypted)',
              'Monthly software updates',
              'GST eInvoice (IRN) setup',
            ].map((item) => (
              <div key={item} className="flex items-center gap-2 text-sm">
                <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0" />
                <span>{item}</span>
              </div>
            ))}
          </div>
          <div className="mt-10 text-center">
            <p className="text-muted-foreground text-sm mb-4">Flexible pricing based on your site requirements</p>
            <a
              href="https://wa.me/917011189371?text=Hi%2C%20I%27d%20like%20to%20know%20the%20pricing%20for%20WeighBridge%20Setu"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button size="lg" className="gap-2">
                <MessageCircle className="h-4 w-4" />
                Get a Custom Quote
              </Button>
            </a>
          </div>
        </div>
      </section>

      {/* ── FAQ ───────────────────────────────────────────── */}
      <section id="faq" className="mx-auto max-w-3xl px-4 sm:px-6 py-16 sm:py-24">
        <div className="text-center mb-10">
          <h2 className="text-3xl sm:text-4xl font-bold">Frequently Asked Questions</h2>
        </div>
        <div className="rounded-xl border border-border bg-background px-6">
          {FAQS.map((faq) => (
            <FAQItem key={faq.q} q={faq.q} a={faq.a} />
          ))}
        </div>
      </section>

      {/* ── CTA Banner ────────────────────────────────────── */}
      <section className="bg-primary text-primary-foreground">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 text-center">
          <h2 className="text-3xl sm:text-4xl font-bold">Ready to Automate Your Weighbridge?</h2>
          <p className="mt-3 text-primary-foreground/80 max-w-xl mx-auto">
            Join 50+ stone crushers who eliminated manual errors, saved hours on Tally entry, and got paid faster.
          </p>
          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
            <a
              href="https://wa.me/917011189371?text=Hi%2C%20I%20want%20to%20book%20a%20free%20demo%20of%20WeighBridge%20Setu"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button size="lg" variant="secondary" className="gap-2 text-base px-8">
                <MessageCircle className="h-4 w-4" />
                Book Free Demo on WhatsApp
              </Button>
            </a>
            <a href="tel:+917011189371">
              <Button size="lg" variant="outline" className="gap-2 text-base px-8 border-primary-foreground/30 text-primary-foreground hover:bg-primary-foreground/10">
                <Phone className="h-4 w-4" />
                +91 70111 89371
              </Button>
            </a>
          </div>
        </div>
      </section>

      {/* ── Footer ────────────────────────────────────────── */}
      <footer id="contact" className="border-t border-border">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-12">
          <div className="grid md:grid-cols-3 gap-8">
            {/* Brand */}
            <div>
              <div className="flex items-center gap-2 mb-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Scale className="h-4 w-4" />
                </div>
                <span className="font-bold">WeighBridge Setu</span>
              </div>
              <p className="text-sm text-muted-foreground leading-relaxed">
                Weighbridge management & GST invoicing software built for Indian stone crushers, mining operations, and aggregate suppliers.
              </p>
            </div>

            {/* Quick Links */}
            <div>
              <h4 className="font-semibold text-sm mb-3">Quick Links</h4>
              <div className="space-y-2 text-sm text-muted-foreground">
                <a href="#why-switch" className="block hover:text-foreground transition-colors">Why Switch</a>
                <a href="#features" className="block hover:text-foreground transition-colors">Features</a>
                <a href="#how-it-works" className="block hover:text-foreground transition-colors">How It Works</a>
                <a href="#results" className="block hover:text-foreground transition-colors">Results</a>
                <a href="#faq" className="block hover:text-foreground transition-colors">FAQ</a>
                <button onClick={() => navigate('/login')} className="block hover:text-foreground transition-colors">
                  Customer Login
                </button>
              </div>
            </div>

            {/* Contact */}
            <div>
              <h4 className="font-semibold text-sm mb-3">Contact Us</h4>
              <div className="space-y-2 text-sm text-muted-foreground">
                <a href="tel:+917011189371" className="flex items-center gap-2 hover:text-foreground transition-colors">
                  <Phone className="h-4 w-4" /> +91 70111 89371
                </a>
                <a href="tel:+917718882113" className="flex items-center gap-2 hover:text-foreground transition-colors">
                  <Phone className="h-4 w-4" /> +91 77188 82113
                </a>
                <a
                  href="https://wa.me/917011189371"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 hover:text-foreground transition-colors"
                >
                  <MessageCircle className="h-4 w-4" /> WhatsApp
                </a>
                <a href="mailto:products@manhotraconsulting.in" className="flex items-center gap-2 hover:text-foreground transition-colors">
                  <Mail className="h-4 w-4" /> products@manhotraconsulting.in
                </a>
                <a href="mailto:contacts@manhotraconsulting.in" className="flex items-center gap-2 hover:text-foreground transition-colors">
                  <Mail className="h-4 w-4" /> contacts@manhotraconsulting.in
                </a>
                <div className="flex items-center gap-2">
                  <MapPin className="h-4 w-4 shrink-0" />
                  <span>J&K, Punjab, UP, UK — All India</span>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-8 pt-6 border-t border-border flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-muted-foreground">
            <p>&copy; {new Date().getFullYear()} Manhotra Consulting. All rights reserved.</p>
            <p>Made with dedication for Indian stone crusher businesses</p>
          </div>
        </div>
      </footer>

      {/* ── Floating WhatsApp Button (Mobile) ─────────────── */}
      <a
        href="https://wa.me/917011189371?text=Hi%2C%20I%20need%20info%20about%20WeighBridge%20Setu"
        target="_blank"
        rel="noopener noreferrer"
        className="fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-green-600 text-white shadow-lg hover:bg-green-700 transition-colors md:hidden"
        aria-label="Chat on WhatsApp"
      >
        <MessageCircle className="h-6 w-6" />
      </a>
    </div>
  );
}
