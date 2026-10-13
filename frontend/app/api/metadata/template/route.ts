import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || "http://backend-svc:5000";
const BACKEND_API_KEY = process.env.BACKEND_API_KEY ?? "";

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/metadata/template`, {
      headers: {
        Authorization: `Bearer ${BACKEND_API_KEY}`,
      },
      cache: "no-store",
    });

    if (!response.ok) {
      let errorMessage = "Failed to download metadata template";
      try {
        const data = await response.json();
        errorMessage = data.error || errorMessage;
      } catch {
        // Backend may return non-JSON for errors.
      }
      return NextResponse.json({ error: errorMessage }, { status: response.status });
    }

    const csvContent = await response.text();
    return new NextResponse(csvContent, {
      status: 200,
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": 'attachment; filename="metadata_template.csv"',
      },
    });
  } catch (error) {
    return NextResponse.json(
      { error: "Failed to download metadata template", details: String(error) },
      { status: 500 },
    );
  }
}
