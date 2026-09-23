"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn, buttonClass } from "@/components/ui";

const APP_LINKS = [
  { href: "/generate", label: "Generate" },
  { href: "/detect", label: "Detect" },
  { href: "/history", label: "History" },
  { href: "/experiments", label: "Experiments" },
];

export function Wordmark() {
  return (
    <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight text-fg">
      <span aria-hidden className="inline-block h-3 w-3 rounded-sm bg-accent" />
      MarkText
    </Link>
  );
}

/* One 64px bar for both the marketing pages and the app; the active route
   is underlined so the user always knows where they are. */
export function Nav({ variant }: { variant: "marketing" | "app" }) {
  const path = usePathname();
  const links = variant === "app" ? APP_LINKS : [{ href: "/#how", label: "How it works" }, { href: "/#results", label: "Results" }, { href: "/about", label: "About" }];
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
        <Wordmark />
        <nav aria-label="Primary" className="hidden items-center gap-1 md:flex">
          {links.map((l) => {
            const active = variant === "app" && path.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-full px-3 py-1.5 text-sm transition-colors",
                  active ? "bg-bg-muted text-fg" : "text-fg-muted hover:text-fg",
                )}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
        <div className="flex items-center gap-2">
          {variant === "marketing" ? (
            <Link href="/generate" className={buttonClass({ size: "sm" })}>
              Open the app
            </Link>
          ) : (
            <Link href="/about" className={buttonClass({ variant: "ghost", size: "sm" })}>
              About
            </Link>
          )}
        </div>
      </div>
      {variant === "app" && (
        <nav aria-label="App sections" className="flex gap-1 overflow-x-auto border-t border-line px-4 py-2 md:hidden">
          {APP_LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={cn(
                "shrink-0 rounded-full px-3 py-1 text-sm",
                path.startsWith(l.href) ? "bg-bg-muted text-fg" : "text-fg-muted",
              )}
            >
              {l.label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}

export function Footer() {
  return (
    <footer className="mt-auto border-t border-line">
      <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-8 text-sm text-fg-muted sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <Wordmark />
        <nav aria-label="Footer" className="flex flex-wrap gap-x-5 gap-y-2">
          <Link href="/generate" className="hover:text-fg">App</Link>
          <Link href="/about" className="hover:text-fg">About</Link>
          <a href="https://github.com/JohnEstano/MarkText" className="hover:text-fg" rel="noreferrer" target="_blank">
            Source
          </a>
          <span>MIT license</span>
        </nav>
      </div>
    </footer>
  );
}
