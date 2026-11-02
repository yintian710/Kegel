<script setup lang="ts">
import { admin, ApiError, type AdminOverviewData, type AdminUser, type AdminVisit, type AdminWallet, type Product, type RewardTier, type SaveProductInput, type Settings } from '../api'
import AdminOverview from '../components/AdminOverview.vue'
import AdminRules from '../components/AdminRules.vue'
import AdminProducts from '../components/AdminProducts.vue'
import AdminRecords from '../components/AdminRecords.vue'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import { useIdentity } from '../composables/useIdentity'
import { ft } from '../composables/usePreferences'

useBodyAttributes({ class:['stage-wrap','admin-page'] })
const tokenKey='checkin_admin_token'
const identity=useIdentity()
const token=ref('')
const tokenInput=ref('')
const data=ref<AdminOverviewData|null>(null)
const busy=ref(false)
const loginError=ref('')
const notice=ref('')
const users=ref<(AdminUser & {balance?:number})[]|null>(null)
let noticeTimer:number|undefined
const confirmDialog=ref<HTMLDialogElement|null>(null)
const creditDialog=ref<HTMLDialogElement|null>(null)
const productPanel=ref<{reset:()=>void}|null>(null)
const action=ref<{title:string;description:string;check:string;secret:boolean;run:(secret:string)=>Promise<unknown>;success:string;afterSuccess?:()=>void}|null>(null)
const confirmed=ref(false), confirmSecret=ref(''), confirmError=ref('')
const creditUser=ref<(AdminWallet|AdminUser)|null>(null)
const creditAmount=ref<number|null>(null), creditSecret=ref(''), creditError=ref('')
const creditRequest=ref<{id:string;amount:string}|null>(null)

function headers(secret=''){return {headers:{'X-Admin-Token':token.value,...(secret?{'X-Secondary-Password':secret}:{})}}}
function message(text:string){notice.value=text;clearTimeout(noticeTimer);noticeTimer=window.setTimeout(()=>notice.value='',4000)}
function errorText(error:unknown){return error instanceof Error?error.message:'操作失败。'}
function handleAuth(error:unknown){if(error instanceof ApiError&&error.status===401){token.value='';data.value=null;try{sessionStorage.removeItem(tokenKey)}catch{}}}
async function refresh(){try{data.value=await admin.overview(headers())}catch(error){handleAuth(error);throw error}}
async function login(){if(busy.value)return;busy.value=true;loginError.value='';token.value=tokenInput.value.trim();try{sessionStorage.setItem(tokenKey,token.value);await refresh();tokenInput.value=''}catch(error){handleAuth(error);loginError.value=errorText(error)}finally{busy.value=false}}
function logout(){try{sessionStorage.removeItem(tokenKey)}catch{}token.value='';data.value=null;users.value=null}
async function refreshClick(){busy.value=true;try{await refresh();message('全部数据已刷新。')}catch(e){message(errorText(e))}finally{busy.value=false}}
function ask(next:NonNullable<typeof action.value>){action.value=next;confirmed.value=false;confirmSecret.value='';confirmError.value='';confirmDialog.value?.showModal()}
async function execute(){if(!action.value||!confirmed.value||busy.value)return;if(action.value.secret&&!confirmSecret.value){confirmError.value='请输入二级密码以确认操作';return}busy.value=true;try{await action.value.run(confirmSecret.value);const {success,afterSuccess}=action.value;action.value=null;confirmDialog.value?.close();afterSuccess?.();message(success);await refresh()}catch(e){handleAuth(e);confirmError.value=errorText(e)}finally{busy.value=false}}
function saveBase(value:Pick<Settings,'deadline'|'min_step_seconds'|'condition_url'>){void direct(async()=>admin.saveSettings(value,headers()),'基础规则已更新。')}
async function direct(run:()=>Promise<unknown>,success:string){if(busy.value)return;busy.value=true;try{await run();await refresh();message(success)}catch(e){handleAuth(e);message(errorText(e))}finally{busy.value=false}}
function saveRewards(tiers:RewardTier[]){if(!data.value)return;ask({title:'保存排名奖励配置',description:'修改排名奖励将调整用户每日打卡可领取的站内积分，请输入二级密码确认操作。',check:'我已核对各档位名次与积分数值，确认保存生效。',secret:true,success:'排名奖励设置已保存。',run:secret=>admin.saveSettings({...data.value!.settings,reward_tiers:tiers,secondary_secret:secret,secondary_password:secret},headers(secret))})}
function review(visit:AdminVisit){ask({title:'批准异常访问',description:`批准用户 ${visit.username||visit.user_id} 的今日打卡资格？标记原因：${visit.reason}`,check:'我已核实访问行为，确认解除限制。',secret:false,success:'操作已成功执行。',run:()=>admin.review({user_id:visit.user_id,approved:true},headers())})}
function openToday(){if(!data.value)return;ask({title:'手动开放今日打卡',description:`确认立即开放 ${data.value.status.day} 的打卡？开放后登录用户可正式参与练习与排名。`,check:'我确认立即开放今日打卡。',secret:false,success:'操作已成功执行。',run:()=>admin.open(headers())})}
function saveProduct(product:SaveProductInput){ask({title:product.id?`确认更新商品 #${product.id}`:'确认上架新商品',description:`商品名称：“${product.name}”，积分售价：${product.points_price} 分，LDC 发货数量：${product.ldc_amount}。购买后将自动调用 Credit 接口发货，请输入二级密码确认。`,check:'我已核对商品售价与发货数量，确认上架/保存。',secret:true,success:product.id?'商品已更新。':'新商品已添加并上架。',afterSuccess:()=>productPanel.value?.reset(),run:secret=>admin.saveProduct({...product,secondary_secret:secret,secondary_password:secret},headers(secret))})}
function archiveProduct(product:Product){ask({title:`确认下架商品 #${product.id}`,description:`确认下架商品 “${product.name}” 吗？下架后用户将无法在商店兑换该商品。请输入二级密码确认。`,check:'我确认下架该商品。',secret:true,success:'商品已下架。',run:secret=>admin.archiveProduct(product.id,headers(secret))})}
async function search(query:string){busy.value=true;try{users.value=(await admin.users(query,headers())).users;message(`找到 ${users.value.length} 位用户，最多显示 50 位。`)}catch(e){handleAuth(e);message(errorText(e))}finally{busy.value=false}}
function openCredit(user:AdminWallet|AdminUser){creditUser.value=user;creditAmount.value=null;creditSecret.value='';creditError.value='';creditRequest.value=null;creditDialog.value?.showModal()}
async function addCredit(){if(!creditUser.value||creditAmount.value===null||busy.value)return;const amount=String(creditAmount.value);if(!creditRequest.value||creditRequest.value.amount!==amount)creditRequest.value={id:crypto.randomUUID(),amount};busy.value=true;let credited=false;try{const result=await admin.addPoints({user_id:creditUser.value.user_id,amount,request_id:creditRequest.value.id,secondary_secret:creditSecret.value},headers(creditSecret.value));credited=true;creditDialog.value?.close();message(`已向 @${result.user.username} 增加 ${result.entry.delta} 积分，当前余额 ${result.wallet.balance}。`);await refresh()}catch(e){handleAuth(e);if(credited)message(`加积分已成功，刷新失败：${errorText(e)}`);else creditError.value=errorText(e)}finally{creditSecret.value='';busy.value=false}}

onMounted(async()=>{if(!await identity.requireLogin('/admin'))return;try{token.value=sessionStorage.getItem(tokenKey)||''}catch{}if(token.value){busy.value=true;try{await refresh()}catch(e){loginError.value=errorText(e)}finally{busy.value=false}}})
</script>

<template>
<div v-if="!data" class="page-wrap" style="max-width:440px;margin-top:10vh"><div class="card"><h1 style="font-size:24px;font-weight:700;margin:0 0 8px">管理员验证</h1><p style="font-size:13px;color:var(--text-muted);margin:0 0 20px">请输入在环境变量 ADMIN_TOKEN 配置的口令进入管理后台。</p><form @submit.prevent="login"><div class="form-group"><label class="form-label">管理员口令</label><input v-model="tokenInput" class="input-text" type="password" required autofocus autocomplete="off" spellcheck="false"></div><p style="font-size:13px;color:#dc2626" role="alert">{{ loginError }}</p><button class="btn-primary" type="submit" style="width:100%" :disabled="busy">进入管理后台 →</button></form></div></div>
<div v-else class="admin-shell"><aside class="admin-sidebar"><div class="admin-sidebar-brand"><img class="brand-logo" :src="'/api/icon?size=48'" alt="Logo"><span>{{ ft('提肛小助手') }}</span><span class="brand-badge" style="background:#e0f2fe;color:#0369a1;border-color:#bae6fd">管理后台</span></div><nav class="admin-nav"><a class="admin-nav-item active" href="#sec-overview">📊 概览监控</a><a class="admin-nav-item" href="#sec-rules">⚙️ 规则配置</a><a class="admin-nav-item" href="#sec-products">🎁 商品管理</a><a class="admin-nav-item" href="#sec-triggers">⏱️ 练习触发</a><a class="admin-nav-item" href="#sec-records">📜 奖励与用户</a></nav><div style="padding-top:16px;border-top:1px solid var(--border-light);display:flex;flex-direction:column;gap:8px"><RouterLink class="btn-secondary" to="/" style="font-size:13px">返回首页</RouterLink><button class="btn-secondary" type="button" style="font-size:13px;color:#dc2626" @click="logout">退出管理</button></div></aside>
<main class="admin-content"><AdminOverview :status="data.status" :settings="data.settings" :busy="busy" @open="openToday" @refresh="refreshClick"/><AdminRules :settings="data.settings" :visits="data.visits" :busy="busy" @save-settings="saveBase" @save-rewards="saveRewards" @review="review"/><AdminProducts ref="productPanel" :products="data.products" :purchases="data.purchases" :busy="busy" @save="saveProduct" @archive="archiveProduct"/><AdminRecords :triggers="data.practice_triggers" :rewards="data.rewards" :wallets="data.wallets" :users="users" :credit-enabled="data.admin_credit_enabled" :busy="busy" @search="search" @credit="openCredit"/></main></div>
<dialog ref="confirmDialog" class="dialog-modal"><form @submit.prevent="execute"><h2 style="font-size:18px;margin:0 0 8px">{{ action?.title }}</h2><p style="font-size:14px;color:var(--text-muted)">{{ action?.description }}</p><div v-if="action?.secret" class="form-group"><label class="form-label">管理员二级密码</label><input v-model="confirmSecret" class="input-text" type="password" autocomplete="off" maxlength="1024"></div><label style="display:flex;gap:8px"><input v-model="confirmed" type="checkbox" required>{{ action?.check }}</label><p style="color:#dc2626;font-size:13px" role="alert">{{ confirmError }}</p><div style="display:flex;gap:12px;justify-content:flex-end"><button class="btn-secondary" type="button" :disabled="busy" @click="confirmDialog?.close()">取消</button><button class="btn-primary" type="submit" :disabled="busy">确认执行</button></div></form></dialog>
<dialog ref="creditDialog" class="dialog-modal"><form @submit.prevent="addCredit"><h2 style="font-size:18px;margin:0 0 8px">增加用户积分</h2><p>@{{ creditUser?.username }} · ID {{ creditUser?.user_id }}<template v-if="creditUser&&'balance' in creditUser"> · 当前 {{ creditUser.balance }} 积分</template></p><div class="form-group"><label class="form-label">增加积分</label><input v-model.number="creditAmount" class="input-text" type="number" min="1" max="100000000" required></div><div class="form-group"><label class="form-label">二级密码</label><input v-model="creditSecret" class="input-text" type="password" required autocomplete="off" maxlength="1024"></div><p style="color:#dc2626" role="alert">{{ creditError }}</p><div style="display:flex;gap:12px;justify-content:flex-end"><button class="btn-secondary" type="button" :disabled="busy" @click="creditDialog?.close()">取消</button><button class="btn-primary" type="submit" :disabled="busy">确认增加积分</button></div></form></dialog>
<div v-if="notice" class="toast-notice" role="status" aria-live="polite">{{ notice }}</div>
</template>
