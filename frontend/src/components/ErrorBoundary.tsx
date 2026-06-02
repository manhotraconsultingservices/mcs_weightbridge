/**
 * Generic React ErrorBoundary.
 *
 * Wraps the routed page tree so that a runtime error in any page renders a
 * friendly fallback (with the actual error message + recovery actions)
 * instead of a blank white screen.
 *
 * Usage:
 *   <ErrorBoundary>
 *     <Routes>…</Routes>
 *   </ErrorBoundary>
 */
import { Component, type ReactNode, type ErrorInfo } from 'react';
import { AlertCircle, RefreshCw, Home } from 'lucide-react';

interface Props {
  children: ReactNode;
  /** Optional callback when an error is caught (e.g. for telemetry). */
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, errorInfo: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // Surface to console for devtools — keeps the stack trace visible to support.
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] runtime error caught:', error, errorInfo);
    this.setState({ errorInfo });
    this.props.onError?.(error, errorInfo);
  }

  handleReset = () => {
    this.setState({ error: null, errorInfo: null });
  };

  render() {
    const { error, errorInfo } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="min-h-[60vh] flex items-center justify-center p-6">
        <div className="max-w-2xl w-full space-y-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-10 w-10 text-rose-500 shrink-0" />
            <div className="flex-1">
              <h1 className="text-xl font-bold text-slate-900">Something went wrong on this page</h1>
              <p className="text-sm text-slate-600 mt-1">
                The page hit an unexpected error. The rest of the app still works — use the buttons below
                to recover, or send this error text to support.
              </p>
            </div>
          </div>

          <pre className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg p-3 whitespace-pre-wrap break-words overflow-x-auto max-h-64">
            {error.name}: {error.message}
            {errorInfo?.componentStack && '\n\n' + errorInfo.componentStack.split('\n').slice(0, 8).join('\n')}
          </pre>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={this.handleReset}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md border border-slate-300 bg-white hover:bg-slate-50 text-sm font-medium"
            >
              <RefreshCw className="h-4 w-4" /> Try again
            </button>
            <a
              href="/"
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md border border-slate-300 bg-white hover:bg-slate-50 text-sm font-medium"
            >
              <Home className="h-4 w-4" /> Go to Dashboard
            </a>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md border border-slate-300 bg-white hover:bg-slate-50 text-sm font-medium"
            >
              Reload page
            </button>
          </div>
        </div>
      </div>
    );
  }
}
