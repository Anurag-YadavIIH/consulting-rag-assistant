"use client";

import { useMeContext } from "../lib/meContext";
import { AskWorkspace } from "../components/ask/AskWorkspace";

export default function AskPage() {
  const { engagement } = useMeContext();
  // Keyed by engagement so switching engagements starts a fresh workspace.
  return <AskWorkspace key={engagement ?? "none"} engagement={engagement} />;
}
