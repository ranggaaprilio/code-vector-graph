import { redirect } from '@sveltejs/kit';

export function load({ params }: { params: { app: string } }) {
	redirect(307, `/apps/${encodeURIComponent(params.app)}/overview`);
}
