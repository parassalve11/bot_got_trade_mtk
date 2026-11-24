"use client";

import Link from "next/link";
import { GroupPage } from "@/components/group-page";

export default function IntradayPage() {
  return (
    <GroupPage
      group="intraday"
      label="15-minute"
      title="Intraday · 15-minute"
      intro={
        <>
          Short-term trades on 15-minute charts, kept separate from the 1-hour swing trades on the{" "}
          <Link href="/positions" className="font-medium text-indigo-600 hover:underline">Positions page</Link> and
          the 5-minute scalps on the{" "}
          <Link href="/scalping" className="font-medium text-indigo-600 hover:underline">Scalping page</Link>.
          A trade usually lasts 15 minutes to a few hours and is closed before the day ends.
        </>
      }
    />
  );
}
