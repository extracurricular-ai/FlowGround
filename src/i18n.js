// Static UI text for Flowground's English/中文 switch. Scope: interface chrome
// only (buttons, labels, hints, tutorial, achievements) — the live run
// console is narrated by the backend in English and is NOT translated here;
// doing that would mean duplicating every narration template server-side.
// User-authored node content (typed messages, expressions, variable names)
// is echoed as-is regardless of language, same reasoning.
export const I18N = {
  en: {
    // block palette: label / description
    b_start_label: 'Start', b_start_desc: 'Begin the flow',
    b_ask_label: 'Ask', b_ask_desc: 'Get a value from the user',
    b_say_label: 'Say', b_say_desc: 'Print a message',
    b_set_label: 'Set variable', b_set_desc: 'Remember a value',
    b_iff_label: 'If', b_iff_desc: 'Choose a path',
    b_loop_label: 'Loop', b_loop_desc: 'Repeat steps',
    b_fn_label: 'Function', b_fn_desc: 'Use a mini-machine',
    b_split_label: 'Split', b_split_desc: 'Run two branches at once',
    b_merge_label: 'Merge', b_merge_desc: 'Wait for every branch, then continue',
    b_subgraph_label: 'Subgraph', b_subgraph_desc: 'A whole mini-flow, packed into one block',
    b_llm_generate_label: 'AI Generate', b_llm_generate_desc: 'Ask an LLM to write something',
    b_llm_judge_label: 'AI Judge', b_llm_judge_desc: 'Let an LLM decide yes or no',
    b_end_label: 'End', b_end_desc: 'Finish the flow',

    // ports
    port_yes: 'yes', port_no: 'no', port_again: 'again', port_done: 'done',

    // achievements
    a_tutorial_label: 'Trained up', a_tutorial_desc: 'Finished the tutorial',
    a_wire_label: 'Wire wizard', a_wire_desc: 'Connected two blocks',
    a_run_label: 'First flight', a_run_desc: 'Ran a flow to the end',
    a_decider_label: 'Decision maker', a_decider_desc: 'Ran an If block',
    a_looper_label: 'Round tripper', a_looper_desc: 'Completed a loop',
    achLocked: ' (locked)',
    achUnlocked: 'Achievement unlocked',

    // tutorial
    tut_0_t: 'Welcome to Flowground',
    tut_0_b: 'Programs are just flows: steps, decisions, and loops. Here you draw them — and then watch them actually run.',
    tut_0_next: 'Show me',
    tut_1_t: 'Your blocks',
    tut_1_b: 'Each block is one instruction. Drag any block onto the canvas — or just click it to drop one in.',
    tut_1_next: 'Next',
    tut_2_t: 'Wire it up',
    tut_2_b: 'Every block has a dot underneath. Drag from a dot to another block to draw an arrow — that is the order things happen. Click a block to edit its words and numbers.',
    tut_2_next: 'Next',
    tut_3_t: 'Press Run',
    tut_3_b: 'Run walks through your flow one block at a time, lighting up the path it takes. Use Step to move one instruction at a time, and the speed switch to slow things down.',
    tut_3_next: 'Next',
    tut_4_t: 'Watch it think',
    tut_4_b: 'Variables show what the flow remembers, and the console tells the story of every step. Ready — press Run and watch the starter flow loop!',
    tut_4_next: 'Let’s go',
    tutStepLabel: 'Tip {n} of {total}',
    tutSkip: 'Skip',

    // inspector field labels
    f_saveAnswerAs: 'Save answer as', f_sampleAnswer: 'Sample answer',
    f_message: 'Message', f_variableName: 'Variable name', f_value: 'Value',
    f_questionToAsk: 'Question to ask', f_loopKind: 'Loop kind',
    f_keepGoingWhile: 'Keep going while', f_timesAround: 'Times around',
    f_miniMachine: 'Mini-machine', f_giveIt: 'Give it', f_saveResultAs: 'Save result as',
    f_prompt: 'Prompt', f_saveReplyAs: 'Save reply as', f_questionForAI: 'Question to ask the AI',

    // inspector hints
    h_ask: 'In a real app the user types the answer — here you choose it in advance.',
    h_say: 'Wrap a variable in {curly braces} to drop it into your sentence.',
    h_set: 'Math (lap + 1), text (hello or hi {name}), or true / false.',
    h_iff: 'Try: count > 3   or   name == "Ada". Yes goes left, no goes right.',
    h_loopWhile: 'A real while-loop: repeats as long as this is true. Change a variable inside the loop — or it never stops!',
    h_loopCount: 'A for-loop: goes around a fixed number of times. Wire the last block of the loop back into this one.',
    h_fn: 'double ×2 · square x·x · shout MAKES IT LOUD',
    h_llmGenerate: 'Wrap a variable in {curly braces}. Uses your AI settings (⚙ in the header) — add an API key there first.',
    h_llmJudge: 'A yes/no question — wrap a variable in {curly braces}. A reply starting with "yes" routes yes, anything else routes no. Uses your AI settings (⚙ in the header).',
    h_start: 'Every flow begins here. There is nothing to set.',
    h_split: 'Both of its arrows fire at once — LoopGraph runs branch A and branch B, one after the other, before anything downstream of both can continue.',
    h_merge: 'Waits for every branch that arrows into it to finish, then continues once — wire both branches of a Split here to join them back up.',
    h_subgraph: 'A whole mini-flow packed into one block, run by LoopGraph as a real nested sub-workflow. Double-click it — or press Open below — to step inside and edit its own Start, blocks and End.',
    h_end: 'When the flow reaches this block, it stops.',
    inspTitleSuffix: '{label} block',

    // header / run controls
    tagline: 'learn logic by drawing it',
    runRun: '▶  Run', runResume: '▶  Resume', runPause: '❚❚  Pause',
    step: 'Step', reset: 'Reset',
    runStatus: 'step {n}', pausedSuffix: ' · paused',
    loadAIExample: 'Load AI example',
    loadAIExampleTitle: 'Replace the canvas with an AI Generate / AI Judge demo flow',
    exportJSON: 'Export JSON', exportJSONTitle: 'Export this flow as JSON',
    aiSettingsTitle: 'AI settings — API key, base URL, compat mode',
    replayTutorial: 'Replay the tutorial',

    // block palette panel
    blocksHeader: 'Blocks',
    dragOrClickToAdd: 'Drag onto the canvas, or click to add',
    dragArrowHint: 'Drag from the dot under a block to another block to draw an arrow.',
    dragToConnect: 'Drag to connect',

    // subgraph / breadcrumb / canvas
    openSubgraph: 'Open subgraph',
    openSubgraphBtn: 'Open subgraph ▸',
    mainFlow: '⌂ Main flow',
    removeBlock: 'Remove block',

    // run panel
    variables: 'Variables',
    varsEmpty: 'Nothing remembered yet — run the flow.',
    console: 'Console',
    consoleEmpty: 'Press Run and watch your flow think out loud.',

    // export modal
    exportFlowTitle: 'Export flow as JSON',
    exportTabLG: 'LoopGraph + Python', exportTabFG: 'Flowground',
    exportDescLG: 'Graph for the LoopGraph engine (nodes, edges, entry) plus a function_registry table — real async Python handlers, one per block. If and Loop blocks become SWITCH routers.',
    exportDescFG: 'Flowground’s own format: blocks with config, ports and canvas positions.',
    copy: 'Copy', copied: 'Copied!', downloadJSON: 'Download .json',

    // AI settings modal
    aiSettings: 'AI settings',
    aiSettingsDesc: 'Powers AI Generate / AI Judge blocks. Kept only in this browser (never in Export JSON) and sent straight to the endpoint below when you Run.',
    compatMode: 'Compat mode',
    modeAnthropic: 'Anthropic (/v1/messages)', modeOpenAI: 'OpenAI-compatible (/chat/completions)',
    baseURL: 'Base URL', apiKey: 'API key', model: 'Model',

    // frontend-generated log lines / errors
    errNoStart: 'Add a Start block first — every flow needs one.',
    serverDown: 'Can’t reach the flow server — is it running? (cd server && uvicorn app.main:app --reload)',

    // subOf() static phrases (mixed with user data — see i18n.js header comment)
    sub_entryPoint: 'entry point',
    sub_runBothBranches: 'run both branches',
    sub_waitForBoth: 'wait for both, then continue',
    sub_allDone: 'all done',
    sub_loopWhile: 'while {cond}', sub_loopCount: '{times}× around',
    sub_nested: 'nested ', sub_loopSuffix: '× loop',
    sub_aiPrefix: 'AI: ', sub_qSuffix: ' ?',

    langToggle: '中文',
  },
  zh: {
    b_start_label: '开始', b_start_desc: '从这里开始流程',
    b_ask_label: '询问', b_ask_desc: '向用户获取一个值',
    b_say_label: '说', b_say_desc: '打印一条消息',
    b_set_label: '设置变量', b_set_desc: '记住一个值',
    b_iff_label: '如果', b_iff_desc: '选择一条路径',
    b_loop_label: '循环', b_loop_desc: '重复步骤',
    b_fn_label: '函数', b_fn_desc: '使用一个小机器',
    b_split_label: '分支', b_split_desc: '同时运行两条分支',
    b_merge_label: '合并', b_merge_desc: '等待每条分支都完成',
    b_subgraph_label: '子图', b_subgraph_desc: '一整个小流程，打包成一个方块',
    b_llm_generate_label: 'AI 生成', b_llm_generate_desc: '让大模型写点什么',
    b_llm_judge_label: 'AI 判断', b_llm_judge_desc: '让大模型判断是或否',
    b_end_label: '结束', b_end_desc: '结束流程',

    port_yes: '是', port_no: '否', port_again: '再来', port_done: '完成',

    a_tutorial_label: '训练有素', a_tutorial_desc: '完成了教程',
    a_wire_label: '接线奇才', a_wire_desc: '连接了两个方块',
    a_run_label: '首次飞行', a_run_desc: '完整运行了一次流程',
    a_decider_label: '决策者', a_decider_desc: '运行了一个「如果」方块',
    a_looper_label: '循环达人', a_looper_desc: '完成了一次循环',
    achLocked: '（未解锁）',
    achUnlocked: '解锁成就',

    tut_0_t: '欢迎来到 Flowground',
    tut_0_b: '程序其实就是流程：步骤、决策和循环。在这里你可以把它们画出来——然后看它们真正运行起来。',
    tut_0_next: '给我看看',
    tut_1_t: '你的方块',
    tut_1_b: '每个方块都是一条指令。把任意方块拖到画布上——或者直接点击它放进去。',
    tut_1_next: '下一步',
    tut_2_t: '连接起来',
    tut_2_b: '每个方块下面都有一个小圆点。从圆点拖到另一个方块上画出一条箭头——这就是执行的顺序。点击方块可以编辑它的文字和数字。',
    tut_2_next: '下一步',
    tut_3_t: '按下运行',
    tut_3_b: '「运行」会一格一格地走完你的流程，并点亮它经过的路径。用「单步」可以一次只走一条指令，用速度开关可以放慢节奏。',
    tut_3_next: '下一步',
    tut_4_t: '看它思考',
    tut_4_b: '「变量」显示流程记住的内容，「控制台」讲述每一步发生的故事。准备好了——按下运行，看看示例流程循环起来吧！',
    tut_4_next: '开始吧',
    tutStepLabel: '第 {n} 条提示，共 {total} 条',
    tutSkip: '跳过',

    f_saveAnswerAs: '保存答案为', f_sampleAnswer: '示例答案',
    f_message: '消息内容', f_variableName: '变量名', f_value: '值',
    f_questionToAsk: '要判断的问题', f_loopKind: '循环类型',
    f_keepGoingWhile: '持续循环的条件', f_timesAround: '循环次数',
    f_miniMachine: '小机器', f_giveIt: '输入', f_saveResultAs: '保存结果为',
    f_prompt: '提示词', f_saveReplyAs: '保存回复为', f_questionForAI: '向 AI 提出的问题',

    h_ask: '在真实的应用里，答案是用户输入的——这里你可以提前替它选好。',
    h_say: '把变量放进 {花括号} 里，就能把它插入到句子中。',
    h_set: '可以是数学运算（lap + 1）、文本（hello 或 hi {name}），或者 true / false。',
    h_iff: '试试看：count > 3　或　name == "Ada"。「是」往左走，「否」往右走。',
    h_loopWhile: '一个真正的 while 循环：只要条件成立就会一直重复。记得在循环里改变某个变量——不然它永远不会停下来！',
    h_loopCount: '一个 for 循环：固定循环若干次。把循环体最后一个方块接回这个方块即可。',
    h_fn: 'double 乘以2 · square 自乘 · shout 变成大写喊出来',
    h_llmGenerate: '把变量放进 {花括号} 里。使用页眉的 AI 设置（⚙）——请先在那里填写 API key。',
    h_llmJudge: '一个是/否问题——把变量放进 {花括号} 里。以「yes」开头的回复会走「是」，其余都走「否」。使用页眉的 AI 设置（⚙）。',
    h_start: '每个流程都从这里开始，没有什么需要设置的。',
    h_split: '它的两条箭头会同时触发——LoopGraph 会依次运行分支 A 和分支 B，然后下游才能继续。',
    h_merge: '等待所有指向它的分支都完成后，才会继续一次——把 Split 的两条分支都接到这里即可汇合。',
    h_subgraph: '一整个小流程打包成一个方块，由 LoopGraph 作为真正的嵌套子流程运行。双击它——或点击下方的「打开子图」——即可进入内部编辑它自己的开始、方块和结束。',
    h_end: '当流程到达这个方块时，就会停止。',
    inspTitleSuffix: '{label} 方块',

    tagline: '画出逻辑，学会编程',
    runRun: '▶  运行', runResume: '▶  继续', runPause: '❚❚  暂停',
    step: '单步', reset: '重置',
    runStatus: '第 {n} 步', pausedSuffix: '·已暂停',
    loadAIExample: '加载 AI 示例',
    loadAIExampleTitle: '用一个 AI 生成 / AI 判断的示例流程替换画布',
    exportJSON: '导出 JSON', exportJSONTitle: '将当前流程导出为 JSON',
    aiSettingsTitle: 'AI 设置 — API key、地址和兼容模式',
    replayTutorial: '重新播放教程',

    blocksHeader: '方块',
    dragOrClickToAdd: '拖到画布上，或点击添加',
    dragArrowHint: '从方块下方的圆点拖到另一个方块上即可画出箭头。',
    dragToConnect: '拖动以连接',

    openSubgraph: '打开子图',
    openSubgraphBtn: '打开子图 ▸',
    mainFlow: '⌂ 主流程',
    removeBlock: '删除方块',

    variables: '变量',
    varsEmpty: '还没有记住任何东西——运行一下试试。',
    console: '控制台',
    consoleEmpty: '按下运行，看你的流程把想法说出来。',

    exportFlowTitle: '将流程导出为 JSON',
    exportTabLG: 'LoopGraph + Python', exportTabFG: 'Flowground',
    exportDescLG: '给 LoopGraph 引擎用的图结构（节点、边、入口），加上一张 function_registry 表——每个方块对应一个真正的异步 Python 处理函数。「如果」和「循环」方块会变成 SWITCH 路由器。',
    exportDescFG: 'Flowground 自己的格式：方块及其配置、端口和画布位置。',
    copy: '复制', copied: '已复制！', downloadJSON: '下载 .json',

    aiSettings: 'AI 设置',
    aiSettingsDesc: '为 AI 生成 / AI 判断方块提供支持。仅保存在本浏览器中（绝不会出现在导出的 JSON 里），运行时会直接发送到下面的接口。',
    compatMode: '兼容模式',
    modeAnthropic: 'Anthropic（/v1/messages）', modeOpenAI: 'OpenAI 兼容（/chat/completions）',
    baseURL: '基础地址', apiKey: 'API 密钥', model: '模型',

    errNoStart: '请先添加一个「开始」方块——每个流程都需要一个。',
    serverDown: '连不上流程服务器——它启动了吗？（cd server && uvicorn app.main:app --reload）',

    sub_entryPoint: '入口',
    sub_runBothBranches: '同时运行两条分支',
    sub_waitForBoth: '等待两者都完成后继续',
    sub_allDone: '全部完成',
    sub_loopWhile: '当 {cond} 时循环', sub_loopCount: '循环 {times} 次',
    sub_nested: '嵌套 ', sub_loopSuffix: ' 次循环',
    sub_aiPrefix: 'AI：', sub_qSuffix: ' ？',

    langToggle: 'EN',
  },
};
