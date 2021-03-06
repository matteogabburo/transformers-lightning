import multiprocessing
from argparse import Namespace

import pytest
import pytorch_lightning as pl
import torch
import transformers_lightning
from torch.utils.data import DataLoader
from transformers import AdamW, BertTokenizer
from transformers.modeling_bert import (BertConfig,
                                        BertForSequenceClassification)

n_cpus = multiprocessing.cpu_count()

class SimpleTransformerLikeModel(transformers_lightning.models.SuperModel):

    def __init__(self, hparams):
        super().__init__(hparams)

        # super light BERT model
        config = BertConfig(hidden_size=12, num_hidden_layers=1, num_attention_heads=1, intermediate_size=12)
        self.model = BertForSequenceClassification(config)
        self.tokenizer = BertTokenizer.from_pretrained("bert-base-cased", config=config, cache_dir=hparams.cache_dir)

    def training_step(self, batch, batch_idx):
        kwargs = {k: batch[k] for k in ["input_ids", "attention_mask", "token_type_ids", "labels"]}
        results = self(**kwargs, return_dict=True)
        return { 'loss': results.loss, 'ids': batch['ids'] }

    def training_step_end(self, batch_parts):
        batch_parts['loss'] = torch.sum(batch_parts['loss'])
        return batch_parts

    def training_epoch_end(self, outputs):
        ids = torch.cat([o['ids'] for o in outputs], dim=0)
        try:
            received = torch.zeros((len(self.datamodule.train_dataset),))
        except TypeError:
            received = torch.zeros((self.datamodule.train_dataset.length,))
        received[ids] = True

        # assert no duplicate element received
        assert len(set(ids.tolist())) == len(ids.tolist()), (
            f"Received {len(ids.tolist())} ids but only {len(set(ids.tolist()))} are unique: {ids}"
        )
        # assert all elements received
        assert all(received), (
            f"({self.trainer.max_steps}) Received not all {len(received)} ids: {received}"
        )

        print("ids: ", ids)

    def validation_step(self, batch, batch_idx):
        kwargs = {k: batch[k] for k in ["input_ids", "attention_mask", "token_type_ids", "labels"]}
        results = self(**kwargs, return_dict=True)
        return results.loss

    def test_step(self, batch, batch_idx):
        kwargs = {k: batch[k] for k in ["input_ids", "attention_mask", "token_type_ids", "labels"]}
        results = self(**kwargs, return_dict=True)
        return results.loss


class ExampleDataModule(transformers_lightning.datamodules.SuperDataModule):

    def __init__(self, *args, ds_type=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.train_config = "dataset.yaml"
 
    train_dataloader = transformers_lightning.datamodules.SuperDataModule.default_train_dataloader



hparams = Namespace(
    batch_size=4,
    val_batch_size=4,
    test_batch_size=4,
    accumulate_grad_batches=3,
    num_workers=n_cpus,
    dataset_dir='tests/test_data',
    config_dir='tests/test_data',
    cache_dir='cache',
    output_dir='output',
    max_epochs=3,
    max_steps=None,
    max_sequence_length=10,
    gpus=2,
    dataset_style='map',
    distributed_backend='ddp'
)


# instantiate PL trainer
trainer = pl.Trainer.from_argparse_args(
    hparams,
    profiler='simple',
    logger=None,
    callbacks=[],
)

# instantiate PL model
model = SimpleTransformerLikeModel(hparams)    

# Datasets
datamodule = ExampleDataModule(hparams, model, trainer)

model.datamodule = datamodule
# Train!
if datamodule.do_train():
    trainer.fit(model, datamodule=datamodule)

# Test!
if datamodule.do_test():
    trainer.test(model, datamodule=datamodule)
