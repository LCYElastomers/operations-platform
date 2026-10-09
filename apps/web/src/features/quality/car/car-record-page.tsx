"use client";

import { AlertTriangle, ArrowLeft, Save } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { siteToday } from "@/features/safety/site-calendar";
import { cn } from "@/lib/utils";

import { carHref, carSaveError, describeCarError, type Car, type CarOptions, type CarResponse } from "./api";
import { draftOf, draftProblems, emptyDraft, fieldsOf, stepOfProblem, type CarDraft, type Problems } from "./car-draft";
import { DraftContext } from "./car-fields";
import { CarError, CarStatusBadge, DueBadge } from "./car-shared";
import {
  CloseStep,
  ContainStep,
  CorrectStep,
  CostStep,
  EvaluateStep,
  HistorySection,
  IdentifyStep,
  InvestigateStep,
  OverviewSection,
  RelatedStep,
  StepStateBadge,
  VerifyStep,
  type StepProps,
} from "./car-steps";
import { useCar, useCarOptions, useCreateCar, useUpdateCar } from "./use-car";

const STEP_VIEWS: Record<string, (props: StepProps) => React.ReactNode> = {
  identify: IdentifyStep,
  contain: ContainStep,
  investigate: InvestigateStep,
  evaluate: EvaluateStep,
  correct: CorrectStep,
  verify: VerifyStep,
  cost: CostStep,
  close: CloseStep,
  related: RelatedStep,
};

/** A new CAR (id null) or an existing one, opened at its overview. */
export function CarRecordPage({ id }: { id: number | null }) {
  const options = useCarOptions();
  const car = useCar(id);
  if (options.isError || car.isError) {
    const error = options.error ?? car.error;
    return (
      <div className="space-y-5">
        <BackToRegister />
        <CarError
          error={error}
          onRetry={() => {
            void options.refetch();
            if (id !== null) void car.refetch();
          }}
        />
      </div>
    );
  }
  if (!options.data || (id !== null && !car.data)) {
    return <p className="py-6 text-sm text-muted-foreground">Loading Corrective Action Report…</p>;
  }
  return <CarWorkspace response={car.data ?? null} options={options.data} />;
}

function BackToRegister() {
  return (
    <Link href="/quality/cars/register" className={buttonVariants({ variant: "ghost", size: "sm" })}>
      <ArrowLeft />
      CAR Register
    </Link>
  );
}

type SaveProblem = { message: string; conflict: boolean };

function CarWorkspace({ response, options }: { response: CarResponse | null; options: CarOptions }) {
  const id = useId();
  const router = useRouter();
  const car = response?.car ?? null;
  const canEdit = response ? response.canEdit : options.canEdit;
  const canEditCost = response ? response.canEditCost : options.canEditCost;
  const [today] = useState(siteToday);
  // The saved CAR the draft was started from: its version is the one saved against.
  const [base, setBase] = useState<Car | null>(car);
  const [draft, setDraft] = useState<CarDraft>(() => (car ? draftOf(car) : emptyDraft(today)));
  const [step, setStep] = useState(car ? "overview" : "identify");
  const [touched, setTouched] = useState(false);
  const [serverProblem, setServerProblem] = useState<{ field: string; message: string } | null>(null);
  const [saveProblem, setSaveProblem] = useState<SaveProblem | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const create = useCreateCar();
  const update = useUpdateCar();
  const pending = create.isPending || update.isPending;

  const baseline = base ? draftOf(base) : emptyDraft(today);
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);

  // Without unsaved edits, follow the latest saved CAR (e.g. after linking a cost record).
  if (car && base && car.version !== base.version && !dirty) {
    setBase(car);
    setDraft(draftOf(car));
  }

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // Action changes do not bump the CAR's version, so their progress comes from the latest CAR.
  const saved = base && car ? { ...base, actions: car.actions } : base;
  const problems: Problems = touched ? draftProblems(draft, today, saved) : {};
  if (serverProblem && !problems[serverProblem.field]) problems[serverProblem.field] = serverProblem.message;
  const problemList = Object.entries(problems).filter((entry): entry is [string, string] => Boolean(entry[1]));

  const updateDraft = (patch: Partial<CarDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    setServerProblem(null);
    setSaveProblem(null);
    setSavedAt(null);
  };

  const save = () => {
    setTouched(true);
    const found = draftProblems(draft, today, saved);
    const first = Object.keys(found)[0];
    if (first) {
      setStep(stepOfProblem(first));
      return;
    }
    const onSuccess = (saved: CarResponse) => {
      setBase(saved.car);
      setDraft(draftOf(saved.car));
      setTouched(false);
      setSavedAt(new Date().toISOString());
      if (!base) router.replace(carHref(saved.car.id));
    };
    const onError = (error: unknown) => {
      const problem = carSaveError(error);
      if (problem?.field) {
        setServerProblem({ field: problem.field, message: problem.message });
        setStep(stepOfProblem(problem.field));
      }
      setSaveProblem({ message: problem?.message ?? describeCarError(error), conflict: problem?.conflict ?? false });
    };
    const body = fieldsOf(draft);
    if (base) update.mutate({ id: base.id, body: { ...body, version: base.version } }, { onSuccess, onError });
    else create.mutate(body, { onSuccess, onError });
  };

  const reload = () => {
    if (!car) return;
    setBase(car);
    setDraft(draftOf(car));
    setSaveProblem(null);
    setServerProblem(null);
    setTouched(false);
  };

  const stepState = new Map(car?.steps.map((s) => [s.code, s.state]) ?? []);
  const nav = [
    ...(car ? [{ code: "overview", label: "Overview" }] : []),
    ...options.steps.map((s, index) => ({ code: s.code, label: `${index + 1} ${s.label}` })),
    { code: "related", label: "Evidence & related" },
    ...(car ? [{ code: "history", label: "History" }] : []),
  ];
  const stepCodes = options.steps.map((s) => s.code);
  const position = stepCodes.indexOf(step);
  const StepView = STEP_VIEWS[step];
  const stepProps: StepProps = { car, options, canEdit, canEditCost, dirty };

  return (
    <DraftContext.Provider value={{ id, draft, update: updateDraft, problems, readOnly: !canEdit }}>
      <div className="space-y-5">
        <BackToRegister />
        <PageHeader
          eyebrow="Quality · Corrective Action Reports"
          title={car ? car.carNumber : "New Corrective Action Report"}
          description={car ? car.subject : "Only the subject and request date are needed to save. Complete the other steps when you can."}
          status={
            car ? (
              <span className="flex flex-wrap gap-1.5">
                <CarStatusBadge car={car} />
                <DueBadge car={car} />
                {car.source === "legacy_import" && <StatusBadge tone="neutral">Imported</StatusBadge>}
              </span>
            ) : undefined
          }
        />
        {!canEdit && (
          <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
            You can view this CAR. Editing needs the quality.cars.edit permission.
          </p>
        )}
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[13rem_1fr]">
          <nav aria-label="CAR steps" className="lg:sticky lg:top-4 lg:self-start">
            <ol className="flex gap-1 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible">
              {nav.map((item) => {
                const state = stepState.get(item.code);
                const hasProblem = problemList.some(([field]) => stepOfProblem(field) === item.code);
                return (
                  <li key={item.code} className="shrink-0">
                    <button
                      type="button"
                      onClick={() => setStep(item.code)}
                      aria-current={step === item.code ? "step" : undefined}
                      className={cn(
                        "flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm whitespace-nowrap pointer-coarse:min-h-11",
                        step === item.code ? "bg-primary/10 font-medium text-primary" : "hover:bg-muted",
                      )}
                    >
                      <span>{item.label}</span>
                      {hasProblem ? (
                        <AlertTriangle className="size-4 text-destructive" aria-label="Has a problem" />
                      ) : (
                        state && (
                          <span
                            aria-label={state.replace("_", " ")}
                            className={cn(
                              "size-2 rounded-full",
                              state === "complete" ? "bg-success" : state === "in_progress" ? "bg-info" : "bg-muted-foreground/30",
                            )}
                          />
                        )
                      )}
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>
          <div className="min-w-0 space-y-4">
            {step === "overview" && car ? (
              <OverviewSection car={car} onOpenStep={setStep} />
            ) : step === "history" && car ? (
              <HistorySection car={car} />
            ) : (
              StepView && (
                <fieldset disabled={!canEdit} className="min-w-0 space-y-4">
                  {stepState.get(step) && (
                    <div className="flex justify-end">
                      <StepStateBadge state={stepState.get(step)!} />
                    </div>
                  )}
                  <StepView {...stepProps} />
                </fieldset>
              )
            )}
            {position >= 0 && (
              <div className="flex justify-between gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={position === 0}
                  onClick={() => setStep(stepCodes[position - 1])}
                >
                  Previous step
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={position === stepCodes.length - 1}
                  onClick={() => setStep(stepCodes[position + 1])}
                >
                  Next step
                </Button>
              </div>
            )}
          </div>
        </div>
        {canEdit && (
          <div className="sticky bottom-0 z-20 -mx-4 border-t bg-background/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
            <div className="flex flex-wrap items-center justify-end gap-3">
              <p className="mr-auto min-w-0 text-sm" role="status" aria-live="polite">
                {saveProblem ? (
                  <span className="text-destructive">{saveProblem.message}</span>
                ) : problemList.length > 0 ? (
                  <span className="text-destructive">
                    {problemList.length === 1 ? problemList[0][1] : `${problemList.length} fields need attention.`}
                  </span>
                ) : dirty ? (
                  <span className="text-muted-foreground">Unsaved changes</span>
                ) : savedAt ? (
                  <span className="text-success">Saved</span>
                ) : null}
              </p>
              {saveProblem?.conflict && (
                <Button variant="outline" onClick={reload}>
                  Discard my changes and load the latest
                </Button>
              )}
              <Button onClick={save} disabled={pending || (!dirty && base !== null)}>
                <Save />
                {pending ? "Saving…" : base ? "Save CAR" : "Create CAR"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </DraftContext.Provider>
  );
}
