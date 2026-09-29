import { Nav, Footer } from "@/components/nav";
import { ApiStatus } from "@/components/status";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Nav variant="app" />
      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6">
        <div className="mb-6">
          <ApiStatus />
        </div>
        {children}
      </main>
      <Footer />
    </>
  );
}
