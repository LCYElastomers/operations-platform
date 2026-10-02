import { MapPinOff } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/common/empty-state";
import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <EmptyState
      icon={MapPinOff}
      title="Page not found"
      description="The page you requested does not exist or has moved."
      action={
        <Link href="/" className={buttonVariants({ variant: "outline" })}>
          Back to overview
        </Link>
      }
    />
  );
}
