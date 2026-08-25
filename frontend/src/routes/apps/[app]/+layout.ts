import { getApp } from '$lib/api/client';

export async function load({ params }: { params: { app: string } }) {
	try {
		const appDetail = await getApp(params.app);
		return { appDetail, appName: params.app, appError: null as string | null };
	} catch (e) {
		return {
			appDetail: null as unknown,
			appName: params.app,
			appError: String((e as Error)?.message || e)
		};
	}
}
