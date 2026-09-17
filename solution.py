import sys
from pathlib import Path
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import StratifiedKFold
import re
import os
import random

def seed_everything(seed=42):
    random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

def parse_panel_token(token):
    m = re.match(r"pt_(\d+)_q(\d+)", token)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0

class Vocab:
    def __init__(self):
        self.w2i = {"<PAD>": 0, "<UNK>": 1}
        self.i2w = {0: "<PAD>", 1: "<UNK>"}

    def add(self, w):
        if w not in self.w2i:
            idx = len(self.w2i)
            self.w2i[w] = idx
            self.i2w[idx] = w

    def __len__(self):
        return len(self.w2i)

    def encode(self, words):
        return [self.w2i.get(w, self.w2i["<UNK>"]) for w in words]

class DissentDataset(Dataset):
    def __init__(self, df, ctx_vocab, rsp_vocab, is_test=False):
        self.df = df.reset_index(drop=True)
        self.ctx_vocab = ctx_vocab
        self.rsp_vocab = rsp_vocab
        self.is_test = is_test

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]

        ctx_seq = self.ctx_vocab.encode(row['context_trace'].split())
        rsp_seq = self.rsp_vocab.encode(row['response_trace'].split())

        panel_tokens = row['panel_trace'].split()
        channels = []
        levels = []
        for t in panel_tokens:
            c, l = parse_panel_token(t)
            channels.append(c)
            levels.append(l)

        def pad_trunc(seq, max_len):
            if len(seq) > max_len:
                return seq[:max_len]
            return seq + [0]*(max_len - len(seq))

        ctx_seq = pad_trunc(ctx_seq, 48)
        rsp_seq = pad_trunc(rsp_seq, 96)
        channels = pad_trunc(channels, 32)
        levels = pad_trunc(levels, 32)

        item = {
            'ctx': torch.tensor(ctx_seq, dtype=torch.long),
            'rsp': torch.tensor(rsp_seq, dtype=torch.long),
            'pnl_c': torch.tensor(channels, dtype=torch.long),
            'pnl_l': torch.tensor(levels, dtype=torch.long),
        }

        if not self.is_test:
            item['target'] = torch.tensor(row['target'], dtype=torch.long)

        return item

class TransformerView(nn.Module):
    def __init__(self, vocab_size, d_model, nhead, num_layers, max_len, is_panel=False, pnl_c_vocab=64, pnl_l_vocab=64):
        super().__init__()
        self.is_panel = is_panel
        if not is_panel:
            self.emb = nn.Embedding(vocab_size, d_model, padding_idx=0)
        else:
            self.c_emb = nn.Embedding(pnl_c_vocab, d_model)
            self.l_emb = nn.Embedding(pnl_l_vocab, d_model)

        self.pos_emb = nn.Embedding(max_len, d_model)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=d_model*4,
            dropout=0.1, activation='gelu', batch_first=True
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)

    def forward(self, x, c=None, l=None):
        seq_len = x.size(1) if x is not None else c.size(1)
        pos = torch.arange(seq_len, device=x.device if x is not None else c.device).unsqueeze(0)

        if not self.is_panel:
            e = self.emb(x)
            padding_mask = (x == 0)
        else:
            e = self.c_emb(c) + self.l_emb(l)
            padding_mask = None

        e = e + self.pos_emb(pos)

        if padding_mask is not None:
            out = self.encoder(e, src_key_padding_mask=padding_mask)
            mask = (~padding_mask).float().unsqueeze(-1)
            return (out * mask).sum(dim=1) / (mask.sum(dim=1) + 1e-8)
        else:
            out = self.encoder(e)
            return out.mean(dim=1)

class DissentModel(nn.Module):
    def __init__(self, ctx_vocab_size, rsp_vocab_size, d_model=256, nhead=8, num_layers=3, dropout=0.2):
        super().__init__()

        self.ctx_view = TransformerView(ctx_vocab_size, d_model, nhead, num_layers, 48)
        self.rsp_view = TransformerView(rsp_vocab_size, d_model, nhead, num_layers, 96)
        self.pnl_view = TransformerView(0, d_model, nhead, num_layers, 32, is_panel=True, pnl_c_vocab=64, pnl_l_vocab=64)

        self.classifier = nn.Sequential(
            nn.Linear(d_model * 3, d_model),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, 5)
        )

    def forward(self, ctx, rsp, pnl_c, pnl_l):
        c_rep = self.ctx_view(ctx)
        r_rep = self.rsp_view(rsp)
        p_rep = self.pnl_view(None, pnl_c, pnl_l)

        combined = torch.cat([c_rep, r_rep, p_rep], dim=1)
        return self.classifier(combined)

def train_and_predict(train_df, test_df, public_dir, submission_out):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Using device: {device}")

    ctx_vocab = Vocab()
    rsp_vocab = Vocab()

    for ctx in train_df['context_trace']:
        for w in ctx.split():
            ctx_vocab.add(w)

    for rsp in train_df['response_trace']:
        for w in rsp.split():
            rsp_vocab.add(w)

    print(f"Ctx vocab size: {len(ctx_vocab)}, Rsp vocab size: {len(rsp_vocab)}")

    test_ds = DissentDataset(test_df, ctx_vocab, rsp_vocab, is_test=True)
    test_loader = DataLoader(test_ds, batch_size=128, shuffle=False, num_workers=2)

    test_preds = np.zeros((len(test_df), 5))

    configs = [
        {"seed": 42, "d_model": 256, "nhead": 8, "num_layers": 3, "epochs": 25},
        {"seed": 100, "d_model": 384, "nhead": 8, "num_layers": 4, "epochs": 25},
        {"seed": 2024, "d_model": 256, "nhead": 4, "num_layers": 3, "epochs": 25}
    ]

    total_models = 0
    batch_size = 64

    for config in configs:
        seed = config["seed"]
        seed_everything(seed)
        print(f"--- Running config: {config} ---")

        kf = StratifiedKFold(n_splits=10, shuffle=True, random_state=seed)

        for fold, (train_idx, val_idx) in enumerate(kf.split(train_df, train_df['target'])):
            print(f"  Fold {fold+1}/10")

            train_sub = train_df.iloc[train_idx]
            val_sub = train_df.iloc[val_idx]

            train_ds = DissentDataset(train_sub, ctx_vocab, rsp_vocab)
            val_ds = DissentDataset(val_sub, ctx_vocab, rsp_vocab)

            train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=2, drop_last=True)
            val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=2)

            model = DissentModel(
                len(ctx_vocab), len(rsp_vocab),
                d_model=config["d_model"],
                nhead=config["nhead"],
                num_layers=config["num_layers"]
            ).to(device)

            optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-2)
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=config["epochs"])
            criterion = nn.CrossEntropyLoss()

            scaler = torch.amp.GradScaler('cuda') if hasattr(torch, 'amp') and hasattr(torch.amp, 'GradScaler') else torch.cuda.amp.GradScaler()

            best_acc = 0.0
            best_model_state = None

            for ep in range(config["epochs"]):
                model.train()
                for batch in train_loader:
                    ctx = batch['ctx'].to(device)
                    rsp = batch['rsp'].to(device)
                    pnl_c = batch['pnl_c'].to(device)
                    pnl_l = batch['pnl_l'].to(device)
                    target = batch['target'].to(device)

                    optimizer.zero_grad()

                    if device.type == 'cuda':
                        with torch.autocast('cuda'):
                            out = model(ctx, rsp, pnl_c, pnl_l)
                            loss = criterion(out, target)
                        scaler.scale(loss).backward()
                        scaler.step(optimizer)
                        scaler.update()
                    else:
                        out = model(ctx, rsp, pnl_c, pnl_l)
                        loss = criterion(out, target)
                        loss.backward()
                        optimizer.step()

                scheduler.step()

                model.eval()
                val_preds_list = []
                val_targs_list = []
                with torch.no_grad():
                    for batch in val_loader:
                        ctx = batch['ctx'].to(device)
                        rsp = batch['rsp'].to(device)
                        pnl_c = batch['pnl_c'].to(device)
                        pnl_l = batch['pnl_l'].to(device)
                        target = batch['target']

                        if device.type == 'cuda':
                            with torch.autocast('cuda'):
                                out = model(ctx, rsp, pnl_c, pnl_l)
                        else:
                            out = model(ctx, rsp, pnl_c, pnl_l)

                        val_preds_list.append(out.argmax(dim=1).cpu())
                        val_targs_list.append(target)

                val_preds_list = torch.cat(val_preds_list)
                val_targs_list = torch.cat(val_targs_list)
                acc = (val_preds_list == val_targs_list).float().mean().item()

                if acc > best_acc:
                    best_acc = acc
best_model_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

            print(f"    Best Val Acc: {best_acc:.4f}")
            if best_model_state is not None:
                model.load_state_dict(best_model_state)

            # Predict on test
            model.eval()
            fold_test_preds = []
            with torch.no_grad():
                for batch in test_loader:
                    ctx = batch['ctx'].to(device)
                    rsp = batch['rsp'].to(device)
                    pnl_c = batch['pnl_c'].to(device)
                    pnl_l = batch['pnl_l'].to(device)

                    if device.type == 'cuda':
                        with torch.autocast('cuda'):
                            out = model(ctx, rsp, pnl_c, pnl_l)
                    else:
                        out = model(ctx, rsp, pnl_c, pnl_l)

                    fold_test_preds.append(torch.softmax(out, dim=1).cpu().numpy())

            fold_test_preds = np.concatenate(fold_test_preds, axis=0)
            test_preds += fold_test_preds
            total_models += 1

    test_preds /= total_models
    final_preds = test_preds.argmax(axis=1)

    submission = pd.DataFrame({
        'id': test_df['id'],
        'prediction': final_preds
    })

    submission_out.parent.mkdir(parents=True, exist_ok=True)
    submission.to_csv(submission_out, index=False)
    print(f"Saved submission to {submission_out}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 solution.py <public_dir> <submission_out>")
        sys.exit(1)

    public_dir = Path(sys.argv[1])
    submission_out = Path(sys.argv[2])

    train = pd.read_csv(public_dir / "train.csv")
    test = pd.read_csv(public_dir / "test.csv")

    train_and_predict(train, test, public_dir, submission_out)
