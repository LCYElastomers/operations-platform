"use client";

import { useDirectory } from "@/features/admin/use-admin";

/** A person on a record: a platform user, or a name recorded before user accounts existed. */
export type Person = { userId: string | null; name: string | null };

const LEGACY = "__recorded__";

/**
 * Chooses a platform user for a person field. Only active users are offered,
 * plus whoever the saved record already names: a former (inactive) user, or a
 * name recorded before user accounts existed, which is kept exactly as written
 * and never matched to a user by guessing.
 */
export function PersonSelect({
  id,
  value,
  recorded,
  onChange,
  placeholder = "Not recorded",
  className,
  ...aria
}: {
  id: string;
  value: Person;
  /** The value saved on the record, so it stays selectable. */
  recorded: Person;
  onChange: (person: Person) => void;
  placeholder?: string;
  className?: string;
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
}) {
  const directory = useDirectory(true);
  const users = directory.data ?? [];
  const legacy = recorded.userId === null && recorded.name ? recorded.name : null;
  const options = users.filter((user) => user.active || user.id === recorded.userId || user.id === value.userId);
  // Keep the saved user selectable while the directory loads (or if it cannot be read).
  if (recorded.userId && !options.some((user) => user.id === recorded.userId)) {
    options.unshift({ id: recorded.userId, name: recorded.name ?? "Recorded user", active: true });
  }
  const selected = value.userId ?? (value.name ? LEGACY : "");

  return (
    <select
      id={id}
      value={selected}
      onChange={(event) => {
        const next = event.target.value;
        if (next === "") onChange({ userId: null, name: null });
        else if (next === LEGACY) onChange({ userId: null, name: legacy });
        else onChange({ userId: next, name: users.find((user) => user.id === next)?.name ?? null });
      }}
      className={className}
      {...aria}
    >
      <option value="">{placeholder}</option>
      {legacy && <option value={LEGACY}>{legacy} (recorded before user accounts)</option>}
      {options.map((user) => (
        <option key={user.id} value={user.id}>
          {user.name}
          {user.active ? "" : " (inactive)"}
        </option>
      ))}
    </select>
  );
}
