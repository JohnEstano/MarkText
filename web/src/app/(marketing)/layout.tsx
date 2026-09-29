import { Nav, Footer } from "@/components/nav";

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Nav variant="marketing" />
      <main id="main" className="flex-1">
        {children}
      </main>
      <Footer />
    </>
  );
}
