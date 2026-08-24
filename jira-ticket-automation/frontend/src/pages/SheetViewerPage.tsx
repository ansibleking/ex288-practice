import { SheetViewer } from "../components/SheetViewer";

export function SheetViewerPage() {
  return (
    <div className="page">
      <header className="page-header">
        <h1>Sheet Viewer</h1>
        <p>Visualize a spreadsheet attachment without opening Excel — upload a file you've downloaded from a ticket.</p>
      </header>
      <SheetViewer />
    </div>
  );
}
