"use client";

import Link from "next/link";
import { GroupPage } from "@/components/group-page";

export default function ScalpingPage() {
  return (
    <GroupPage
      group="scalping"
      label="5-minute"
      title="Scalping · 5-minute"
      intro={
        <>
          Quick trades on 1- and 5-minute charts with small targets, kept separate from the{" "}
          <Link href="/intraday" className="font-medium text-indigo-600 hover:underline">Intraday</Link> and{" "}
          <Link href="/positions" className="font-medium text-indigo-600 hover:underline">swing</Link> trades.
          A trade usually lasts minutes to an hour.
        </>
      }
    />
  );
}
