import pickle
import torch
import os
import numpy as np


class Clause_feature:
    def __init__(self, tk_idx, tk, offset, pos, ner, dep, bert_offset):
        self.tk_idx = tk_idx
        self.tk = tk
        self.offset = offset
        self.pos = pos
        self.ner = ner
        self.dep = dep
        self.bert_offset = bert_offset

# *** Select a preprocessing method
def sel_preprocessing(_input="stanza"):
    # 1. Stanza
    if _input.lower() == "stanza":
        import stanza
        return stanza.Pipeline('en')

    elif _input.lower() == "spacy":
        # 2. Spacy
        import spacy
        return spacy.load("en_core_web_sm")


# *** Select a pre-trained Word Embeddings
def sel_pretrained(_input="bert"):
    # 1. BERT
    if _input.lower() == "bert":
        print("****** Selected pretrained word embeddings: {}".format(_input))
        from transformers import BertConfig, BertModel, BertTokenizerFast, BertForSequenceClassification, AdamW, BertPreTrainedModel
        PRETRAINED_BERT = "bert-base-uncased"
        return BertModel.from_pretrained(PRETRAINED_BERT), BertTokenizerFast.from_pretrained(PRETRAINED_BERT)

    # 2. Elmo
    elif _input.lower() == "elmo":
        print("****** Selected pretrained word embeddings: {}".format(_input))
        from allennlp.commands.elmo import ElmoEmbedder
        return None, ElmoEmbedder(cuda_device=0)

    # 3. Glove
    elif _input.lower() == "glove42b":
        print("****** Selected pretrained word embeddings: {}".format(_input))
        glove_PATH = "./glove/glove.42B.300d.pkl"
        with open(glove_PATH, "rb") as file:
            glove = pickle.load(file)
        return None, glove

    elif _input.lower() == "glove840b":
        print("****** Selected pretrained word embeddings: {}".format(_input))
        glove_PATH = "./glove/glove.840B.300d.pkl"
        with open(glove_PATH, "rb") as file:
            glove = pickle.load(file)
        return None, glove

# *** Tokenize with selected method and store with token-level id, text, offset, pos tag, ner and dependency triple
def tokenization_processing(_datasample, nlp, _pipeline='stanza'):
    cur_clause_feature = []
    # Spacy
    if _pipeline == "spacy":
        print("****** Selected preprocessing method: {}".format(_pipeline))
        doc = nlp(_datasample)
        for tk_idx, tk in enumerate(doc):
            cur_tk = tk.text
            cur_id = tk_idx+1
            cur_head = tk.head.i

            cur_tk_start_offset = tk.idx
            cur_tk_end_offset = tk.idx + len(tk)

            cur_pos = tk.pos_
            cur_ner = tk.ent_type_
            cur_dep = tk.dep_

            cur_dep_triple = (cur_id, cur_dep, cur_head)

            cur_clause_feature.append(Clause_feature(cur_id, cur_tk, (cur_tk_start_offset, cur_tk_end_offset), cur_pos, cur_ner, cur_dep_triple, ''))
    # Stanza
    elif _pipeline == "stanza":
        print("****** Selected preprocessing method: {}".format(_pipeline))
        doc = nlp(_datasample)
        for sen in doc.sentences:
            for tk in sen.tokens:
                tk_infor_dict = tk.to_dict()[0]
                cur_tk = tk_infor_dict["text"]
                cur_id = tk_infor_dict['id']
                cur_head = tk_infor_dict['head']

                offsets = tk_infor_dict['misc'].split("|")
                cur_tk_start_offset = int(offsets[0].split("=")[1])
                cur_tk_end_offset = int(offsets[1].split("=")[1])

                cur_pos = tk_infor_dict["xpos"]
                cur_ner = tk_infor_dict["ner"]

                cur_dep = tk_infor_dict["deprel"]

                cur_dep_triple = (cur_id, cur_dep, cur_head)

                cur_clause_feature.append(Clause_feature(cur_id, cur_tk, (cur_tk_start_offset, cur_tk_end_offset), cur_pos, cur_ner, cur_dep_triple, ''))
    return cur_clause_feature


def embedding2preprocessed(args, datasample, nlp, embedder, model):
    # preprocessed result
    preprocessed_result = tokenization_processing(datasample, nlp, args.pipeline)

    if args.emb == "bert":
        # bert tokenized result
        tokenized_result = embedder(datasample, return_offsets_mapping=True, return_tensors='pt')

        for p_idx, p_result in enumerate(preprocessed_result):
            p_offset = p_result.offset
            p_start_offset = p_offset[0]
            p_end_offset = p_offset[1]

            cur_offset_list = []
            for b_idx, b_offset in enumerate(tokenized_result['offset_mapping'][1:-1]):
                b_start_offset = b_offset[0]
                b_end_offset = b_offset[1]

                # offset of the bert tokenized token is in the preprocessed offset
                if b_start_offset >= p_start_offset and b_end_offset <= p_end_offset:
                    if len(cur_offset_list) == 0:
                        cur_offset_list = [b_idx+1]
                    else:
                        cur_offset_list.append(b_idx+1)

            p_result.bert_offset = cur_offset_list

        # The output type: Frozen word embeddings
        if args.output_type == "frozen":
            bert_embedding = model(input_ids=tokenized_result['input_ids'],
                                  attention_mask=tokenized_result['attention_mask'],
                                  token_type_ids=tokenized_result['token_type_ids'])[0]

            bert_embedding = torch.squeeze(bert_embedding, 0)
            return {'emb':bert_embedding,
                     'preprocessed_offset_match':[x.bert_offset for x in preprocessed_result],
                     'preprocessed_dep': [x.dep for x in preprocessed_result]}

        # The output type: BERT model input
        else:
            return {'input_ids':tokenized_result['input_ids'],
                 'attention_mask':tokenized_result['attention_mask'],
                 'token_type_ids':tokenized_result['token_type_ids'],
                 'preprocessed_offset_match':[x.bert_offset for x in preprocessed_result],
                 'preprocessed_dep': [x.dep for x in preprocessed_result]}


    elif args.emb =="elmo":
        elmo_embedding = embedder.embed_sentence([x.tk for x in preprocessed_result])[0]
        elmo_embedding = torch.tensor(elmo_embedding)

        return {'emb':elmo_embedding,
                 'preprocessed_offset_match':[[x.tk_idx] for x in preprocessed_result],
                 'preprocessed_dep': [x.dep for x in preprocessed_result]}

    elif 'glove' in args.emb:
        glove_emb = []

        for x in preprocessed_result:
            cur_tk = x.tk.lower()
            if cur_tk in embedder:
                cur_emb = embedder[cur_tk]
            else:
                cur_emb = np.zeros(300)
            glove_emb.append(cur_emb)
        glove_emb = torch.tensor(glove_emb)

        return {'emb':glove_emb,
                 'preprocessed_offset_match':[[x.tk_idx] for x in preprocessed_result],
                 'preprocessed_dep': [x.dep for x in preprocessed_result]}