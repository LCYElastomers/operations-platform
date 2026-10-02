import { ApiStatus } from "@/components/system/api-status";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center gap-6 px-6 py-16">
      <div className="space-y-2">
        <p className="text-xs font-semibold tracking-widest text-muted-foreground uppercase">
          LCY
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">Operations Platform</h1>
        <p className="text-sm text-muted-foreground">
          Project skeleton. Modules will be added here.
        </p>
      </div>
      <section aria-label="System status" className="space-y-2">
        <h2 className="text-sm font-medium text-muted-foreground">System status</h2>
        <ApiStatus />
      </section>
    </main>
  );
}
