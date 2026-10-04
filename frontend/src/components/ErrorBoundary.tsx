// Sources: https://react.dev/reference/react/Component#catching-rendering-errors-with-an-error-boundary
import { Component, type ReactNode } from "react";

/** Keeps a render crash in one page from blanking the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (!this.state.error) return this.props.children;
    return <p role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">This page failed to render: {this.state.error.message}</p>;
  }
}
