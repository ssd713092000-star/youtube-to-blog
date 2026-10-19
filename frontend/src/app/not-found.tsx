import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 px-6 text-center">
      <p className="font-mono text-sm text-fg-subtle">404</p>
      <h1 className="text-xl font-semibold">We couldn't find that page.</h1>
      <Link href="/dashboard" className="text-sm text-accent hover:underline">
        Back to the dashboard
      </Link>
    </div>
  );
}
