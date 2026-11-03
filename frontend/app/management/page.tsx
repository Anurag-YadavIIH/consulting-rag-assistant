"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * The old Management placeholder moved to /activity/. A static export can't
 * use server redirects (next.config `redirects` don't run), so this page
 * replaces itself on the client and offers a link meanwhile.
 */
export default function ManagementRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/activity/");
  }, [router]);

  return (
    <p className="text-sm text-muted">
      This page moved to{" "}
      <Link href="/activity/" className="text-link underline">
        Activity
      </Link>
      .
    </p>
  );
}
