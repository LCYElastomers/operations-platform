import { cn } from "@/lib/utils";

type SectionHeadingProps = {
  children: React.ReactNode;
  id?: string;
  className?: string;
  /** HTML heading level. Defaults to h2 for major content sections. */
  as?: "h2" | "h3" | "h4";
};

/** Major section title with a short vertical interaction accent. */
export function SectionHeading({ children, id, className, as: Tag = "h2" }: SectionHeadingProps) {
  return (
    <Tag id={id} className={cn("section-accent text-sm font-semibold tracking-tight", className)}>
      {children}
    </Tag>
  );
}
