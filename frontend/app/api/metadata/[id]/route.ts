import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://backend-svc:5000';
const API_KEY = process.env.BACKEND_API_KEY ?? '';

interface Params {
  id: string;
}

/**
 * GET /api/metadata/[id]
 * Fetches a specific metadata record
 * Proxies to Flask backend: GET /api/metadata/{id}
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<Params> }
) {
  try {
    const resolvedParams = await params;
    const { id } = resolvedParams;

    const backendUrl = `${BACKEND_URL}/api/metadata/${id}`;

    console.log(`[API] GET /api/metadata/${id} - Proxying to: ${backendUrl}`);

    const response = await fetch(backendUrl, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${API_KEY}`,
        'Content-Type': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      console.error(`[API] Backend returned ${response.status}:`, data);
      return NextResponse.json(
        { error: data.error || 'Failed to fetch metadata' },
        { status: response.status }
      );
    }

    console.log(`[API] Successfully fetched metadata record: ${id}`);
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error(`[API] Error fetching metadata:`, error);
    return NextResponse.json(
      { error: 'Failed to fetch metadata', details: String(error) },
      { status: 500 }
    );
  }
}

/**
 * PUT /api/metadata/[id]
 * Updates a metadata record
 * Proxies to Flask backend: PUT /api/metadata/{id}
 */
export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<Params> }
) {
  try {
    const resolvedParams = await params;
    const { id } = resolvedParams;
    const body = await request.json();

    const backendUrl = `${BACKEND_URL}/api/metadata/${id}`;

    console.log(`[API] PUT /api/metadata/${id} - Proxying request with body:`, body);

    const response = await fetch(backendUrl, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();

    if (!response.ok) {
      console.error(`[API] Backend returned ${response.status}:`, data);
      return NextResponse.json(
        { error: data.error || 'Failed to update metadata' },
        { status: response.status }
      );
    }

    console.log(`[API] Successfully updated metadata record: ${id}`);
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error(`[API] Error updating metadata:`, error);
    return NextResponse.json(
      { error: 'Failed to update metadata', details: String(error) },
      { status: 500 }
    );
  }
}

/**
 * DELETE /api/metadata/[id]
 * Deletes a metadata record
 * Proxies to Flask backend: DELETE /api/metadata/{id}
 */
export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<Params> }
) {
  try {
    const resolvedParams = await params;
    const { id } = resolvedParams;

    const backendUrl = `${BACKEND_URL}/api/metadata/${id}`;

    console.log(`[API] DELETE /api/metadata/${id} - Proxying request`);

    const response = await fetch(backendUrl, {
      method: 'DELETE',
      headers: {
        'Authorization': `Bearer ${API_KEY}`,
        'Content-Type': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      console.error(`[API] Backend returned ${response.status}:`, data);
      return NextResponse.json(
        { error: data.error || 'Failed to delete metadata' },
        { status: response.status }
      );
    }

    console.log(`[API] Successfully deleted metadata record: ${id}`);
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error(`[API] Error deleting metadata:`, error);
    return NextResponse.json(
      { error: 'Failed to delete metadata', details: String(error) },
      { status: 500 }
    );
  }
}
