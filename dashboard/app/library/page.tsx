import { library, type Subject } from "../../lib/library";
import LibraryView from "./LibraryView";

export const dynamic = "force-dynamic";

export default async function LibraryPage() {
  let subjects: Subject[] = [];
  let error = "";
  try {
    subjects = await library();
  } catch (e) {
    error = "Michael's backend is not running. Start it from Obsidian or with: michael serve";
  }
  if (error) return <div className="card error">{error}</div>;

  return (
    <>
      <div className="row between">
        <h1 className="page-title">Library</h1>
        <form action="/search" className="row"><input name="q" placeholder="Search every note…" /><button>Search</button></form>
      </div>
      <LibraryView subjects={subjects} />
    </>
  );
}
