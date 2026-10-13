import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://backend-svc:5000';
const BACKEND_API_KEY = process.env.BACKEND_API_KEY ?? '';

/**
 * POST /api/metadata/import
 * Imports metadata from Excel file
 * Proxies to Flask backend: POST /api/metadata/import
 */
export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get('file');

    if (!file || !(file instanceof File)) {
      return NextResponse.json(
        { error: 'No file provided' },
        { status: 400 }
      );
    }

    console.log(`[API] POST /api/metadata/import - File: ${file.name}, Size: ${file.size} bytes`);

    // Create new FormData for backend request
    const backendFormData = new FormData();
    backendFormData.append('file', file);

    const backendUrl = `${BACKEND_URL}/api/metadata/import`;

    // Call Flask backend
    // NOTE: Do NOT set Content-Type header - fetch will set it automatically for FormData
    const response = await fetch(backendUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${BACKEND_API_KEY}`,
      },
      body: backendFormData,
    });

    // Check if response is JSON before parsing
    const contentType = response.headers.get('content-type');
    if (!contentType || !contentType.includes('application/json')) {
      const text = await response.text();
      console.error(`[API] Backend returned non-JSON content type (${contentType}):`, text.substring(0, 500));
      return NextResponse.json(
        { error: `Backend error: ${text.substring(0, 200)}` },
        { status: response.status }
      );
    }

    const data = await response.json();

    if (!response.ok) {
      console.error(`[API] Backend returned ${response.status}:`, data);
      return NextResponse.json(
        { error: data.error || 'Failed to import metadata' },
        { status: response.status }
      );
    }

    console.log(`[API] Successfully imported metadata - Imported: ${data.imported}, Skipped: ${data.skipped}, Errors: ${data.errors}`);
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error('[API] Error importing metadata:', error);
    return NextResponse.json(
      { error: 'Failed to import metadata', details: String(error) },
      { status: 500 }
    );
  }
}
